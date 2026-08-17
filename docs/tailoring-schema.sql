-- =============================================================================
-- Tailoring pipeline schema  (DESIGN ONLY — not yet created by app/db.py)
-- =============================================================================
--
-- Supports this workflow:
--   1. Import jobs (company, title, url, description).
--   2. Extract tech skills + job mission from the description via DeepSeek/ChatGPT.
--   3. Embed the bullet library, semantic-search it, pick 2 companies, then
--      pick the final bullets for those companies.
--   4. Generate a tailored resume + cover letter PDF into the output folder.
--
-- Design notes that drove the shape:
--
--   * The relational tables are the source of truth; the Job.json /
--     Bullets.json documents in the brief are *projections* of them (see the
--     views at the bottom). Storing only JSON blobs would make "which bullets
--     came from which company" unqueryable, which step 3 of the selection
--     strategy depends on.
--
--   * Embeddings are cached and keyed by a hash of the bullet text. Re-encoding
--     the whole library on every Generate click would dominate runtime, and a
--     stale cache after an edit is the obvious failure mode, so invalidation is
--     built into the key rather than left to callers.
--
--   * Every selection step is recorded (frequency counts, scores, ranks). The
--     ranking is the part most likely to need tuning, and without an audit
--     trail "why did it pick these two companies?" is unanswerable.
--
--   * Company slots are fixed by category, not by raw frequency:
--
--         current  (most recent role) -> category 'faang'
--         previous (earlier role)     -> category 'startup'
--
--     Frequency therefore ranks *within* a category, picking the best-matching
--     FAANG company and the best-matching startup, rather than the global top
--     two (which could return two FAANG companies and break the intended
--     career progression). This pairing is enforced by a CHECK on
--     job_company_selection, so an invalid combination cannot be stored even
--     if the selection code has a bug.
--
--     Consequence worth knowing: the library must contain at least one active
--     'faang' company and one active 'startup' company with bullets, or
--     selection has nothing to choose from. See v_selection_eligibility.
--
--   * Generated files are recorded as immutable rows, consistent with the
--     existing generated_resumes table: re-generating adds a row, it does not
--     mutate history.
--
-- Conventions match app/db.py: TEXT ids, ISO-8601 TEXT timestamps, JSON in
-- TEXT columns, PRAGMA foreign_keys = ON.


-- =============================================================================
-- 1. Bullet library   (source shape: Bullets.json)
-- =============================================================================

-- Bullets.json top level: { "Company Name": { "Product": [ ... ] } }
--
-- Companies are a table rather than a plain string on `bullets` because the
-- selection strategy needs per-company attributes: `category` drives the
-- startup-vs-FAANG role assignment, and `active` lets a company be retired
-- without deleting history.
CREATE TABLE bullet_companies (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,          -- key in Bullets.json
    -- Determines which experience slot this company can fill:
    --   'faang'   -> eligible for the most recent role only
    --   'startup' -> eligible for the earlier role only
    --   'other'   -> never selected as an employer; its bullets are still
    --                embedded and can inform ranking, but it cannot be chosen.
    category      TEXT NOT NULL DEFAULT 'other'
                  CHECK (category IN ('faang', 'startup', 'other')),
    display_name  TEXT,                          -- optional resume-facing name
    location      TEXT NOT NULL DEFAULT '',
    -- Free-form default dates for the rendered experience entry.
    default_start TEXT NOT NULL DEFAULT '',
    default_end   TEXT NOT NULL DEFAULT '',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Second level of Bullets.json. Nullable on `bullets` so a company can hold
-- bullets that aren't tied to a product.
CREATE TABLE bullet_products (
    id          TEXT PRIMARY KEY,
    company_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (company_id, name),
    FOREIGN KEY (company_id) REFERENCES bullet_companies(id) ON DELETE CASCADE
);

CREATE TABLE bullets (
    id          TEXT PRIMARY KEY,
    company_id  TEXT NOT NULL,
    product_id  TEXT,                            -- NULL = company-level bullet
    text        TEXT NOT NULL,
    -- Deactivating keeps historical selections resolvable; deleting would
    -- orphan them.
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES bullet_companies(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES bullet_products(id)  ON DELETE SET NULL
);

CREATE INDEX idx_bullets_company ON bullets(company_id);
CREATE INDEX idx_bullets_active  ON bullets(active);


-- =============================================================================
-- 2. Embedding cache   (sentence-transformers)
-- =============================================================================

-- One row per (bullet, model). Keeping the model in the key means switching
-- from all-MiniLM-L6-v2 to another model doesn't silently mix vector spaces —
-- cosine similarity across two different models is meaningless.
CREATE TABLE bullet_embeddings (
    bullet_id   TEXT NOT NULL,
    model       TEXT NOT NULL,                   -- e.g. 'all-MiniLM-L6-v2'
    dim         INTEGER NOT NULL,                -- 384 for MiniLM-L6
    vector      BLOB NOT NULL,                   -- float32 array, little-endian
    -- SHA-256 of bullets.text at encode time. If the text is edited the hash
    -- stops matching and the row is recomputed rather than served stale.
    text_hash   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (bullet_id, model),
    FOREIGN KEY (bullet_id) REFERENCES bullets(id) ON DELETE CASCADE
);

CREATE INDEX idx_embeddings_model ON bullet_embeddings(model);


-- =============================================================================
-- 3. Imported jobs   (source shape: Job.json)
-- =============================================================================

-- One row per imported job. Jobs are currently held only in browser state;
-- this persists them so status and generated output survive a reload.
CREATE TABLE job_applications (
    id                  TEXT PRIMARY KEY,
    -- Which resume profile this application was tailored from.
    profile_id          TEXT,
    -- Display order from the imported file ("No" column).
    row_no              INTEGER,

    -- --- imported columns ---------------------------------------------------
    company             TEXT NOT NULL DEFAULT '',
    job_title           TEXT NOT NULL DEFAULT '',
    job_url             TEXT NOT NULL DEFAULT '',
    job_description     TEXT NOT NULL DEFAULT '',   -- Job.json: jobDescription

    -- --- step 1: LLM extraction --------------------------------------------
    -- Job.json: techSkillsExtracted. JSON array of strings.
    tech_skills_json    TEXT NOT NULL DEFAULT '[]',
    -- Second half of the hybrid search query.
    job_mission         TEXT NOT NULL DEFAULT '',
    -- Which provider produced the extraction, for reproducibility.
    extraction_model    TEXT,
    extracted_at        TEXT,

    -- --- step 2: bullet selection ------------------------------------------
    -- Job.json: bulletsExtracted. Denormalised copy of job_selected_bullets,
    -- kept for easy export; job_selected_bullets remains authoritative.
    bullets_extracted_json TEXT NOT NULL DEFAULT '[]',
    -- The exact query string fed to the encoder, so a result can be explained.
    search_query        TEXT NOT NULL DEFAULT '',

    -- --- step 3: generated output ------------------------------------------
    -- "one column for generated pdf file" — the latest resume. Full history
    -- lives in generated_documents.
    resume_pdf_path     TEXT,
    cover_letter_path   TEXT,
    -- [mm-dd-yy]_[Company]_[Job Title] folder this job's files were written to.
    output_folder       TEXT,

    -- --- state --------------------------------------------------------------
    -- User-facing status from the brief.
    status              TEXT NOT NULL DEFAULT 'Pending'
                        CHECK (status IN ('Pending', 'Applied', 'Expired')),
    -- Pipeline state, separate from `status`: a job can be Pending yet have a
    -- failed generation, and conflating them would hide errors.
    generation_state    TEXT NOT NULL DEFAULT 'none'
                        CHECK (generation_state IN
                               ('none', 'queued', 'running', 'complete', 'failed')),
    generation_error    TEXT,
    generated_at        TEXT,

    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE SET NULL
);

CREATE INDEX idx_jobs_profile ON job_applications(profile_id);
CREATE INDEX idx_jobs_status  ON job_applications(status);


-- =============================================================================
-- 4. Selection audit
-- =============================================================================

-- Step 3-5 of the company strategy: how often each company appeared in the
-- top-N sample, and which role slot it was assigned.
--
-- Stored rather than recomputed because the ranking is the piece most likely to
-- need tuning; without it there is no way to answer "why these two companies?".
CREATE TABLE job_company_selection (
    job_application_id TEXT NOT NULL,
    company_id         TEXT NOT NULL,
    -- 'current'    = most recent role   (must be a FAANG company)
    -- 'previous'   = earlier role       (must be a startup)
    -- 'considered' = appeared in the top-N sample but wasn't chosen; kept so a
    --                near-miss is visible when tuning the ranking.
    role_slot          TEXT NOT NULL
                       CHECK (role_slot IN ('current', 'previous', 'considered')),
    -- Snapshot of bullet_companies.category at selection time. Denormalised on
    -- purpose: it lets the pairing below be enforced by a CHECK (SQLite CHECK
    -- cannot reference another table), and it keeps a historical selection
    -- explainable even if the company is later recategorised.
    company_category   TEXT NOT NULL
                       CHECK (company_category IN ('faang', 'startup', 'other')),
    match_count        INTEGER NOT NULL DEFAULT 0,  -- hits in the top-N sample
    rank               INTEGER NOT NULL,
    -- The rule, enforced by the database rather than trusted to the caller:
    -- the recent role is always FAANG and the earlier role always a startup.
    CHECK (
        (role_slot = 'current'    AND company_category = 'faang')   OR
        (role_slot = 'previous'   AND company_category = 'startup') OR
        (role_slot = 'considered')
    ),
    PRIMARY KEY (job_application_id, company_id),
    FOREIGN KEY (job_application_id) REFERENCES job_applications(id) ON DELETE CASCADE,
    -- RESTRICT, deliberately: a company referenced by a past selection cannot be
    -- deleted, because that would leave a generated resume citing a company the
    -- database can no longer name. Retire a company with active = 0 instead.
    FOREIGN KEY (company_id)         REFERENCES bullet_companies(id) ON DELETE RESTRICT
);

-- Exactly one company may hold each real slot per job. Without this, a retry
-- that re-ran selection could leave two 'current' rows and the renderer would
-- silently pick whichever came back first. 'considered' is unconstrained.
CREATE UNIQUE INDEX idx_one_company_per_slot
    ON job_company_selection(job_application_id, role_slot)
    WHERE role_slot IN ('current', 'previous');

-- Step 7: the final bullets, with the score and ordering that produced them.
CREATE TABLE job_selected_bullets (
    job_application_id TEXT NOT NULL,
    bullet_id          TEXT NOT NULL,
    -- Which rendered experience entry this bullet belongs to.
    role_slot          TEXT NOT NULL CHECK (role_slot IN ('current', 'previous')),
    -- Cosine similarity from util.semantic_search.
    score              REAL NOT NULL,
    -- Order within the role, so the rendered order is reproducible.
    position           INTEGER NOT NULL,
    PRIMARY KEY (job_application_id, bullet_id),
    FOREIGN KEY (job_application_id) REFERENCES job_applications(id) ON DELETE CASCADE,
    -- RESTRICT for the same reason as above. Note this also blocks deleting a
    -- *company* whose bullets were used, since that would cascade into here —
    -- which is the intended protection, not an accident.
    FOREIGN KEY (bullet_id)          REFERENCES bullets(id) ON DELETE RESTRICT
);

CREATE INDEX idx_selected_bullets_job ON job_selected_bullets(job_application_id, role_slot, position);


-- =============================================================================
-- 5. Generated documents
-- =============================================================================

-- Immutable history for both document kinds, mirroring generated_resumes.
-- job_applications.resume_pdf_path points at the newest resume row; this keeps
-- every earlier one so a regenerate never destroys what was already sent.
CREATE TABLE generated_documents (
    id                 TEXT PRIMARY KEY,
    job_application_id TEXT,
    profile_id         TEXT,
    kind               TEXT NOT NULL CHECK (kind IN ('resume', 'cover_letter')),
    template_id        TEXT,
    template_version   INTEGER,
    file_name          TEXT NOT NULL,
    file_path          TEXT NOT NULL,
    -- SHA-256 over the inputs that determined the document.
    content_hash       TEXT,
    -- Snapshots so a historical document stays reproducible after later edits.
    profile_snapshot_json TEXT NOT NULL DEFAULT '{}',
    style_snapshot_json   TEXT NOT NULL DEFAULT '{}',
    bullets_snapshot_json TEXT NOT NULL DEFAULT '[]',
    generated_at       TEXT NOT NULL,
    FOREIGN KEY (job_application_id) REFERENCES job_applications(id) ON DELETE SET NULL,
    FOREIGN KEY (profile_id)         REFERENCES profiles(id)         ON DELETE SET NULL
);

CREATE INDEX idx_generated_docs_job ON generated_documents(job_application_id, kind, generated_at);


-- =============================================================================
-- 6. Views — the JSON shapes from the brief, derived rather than duplicated
-- =============================================================================

-- Bullets.json, flattened. Grouping into the nested
-- { company: { product: [...] } } document happens in application code.
CREATE VIEW v_bullet_library AS
SELECT
    c.name          AS company_name,
    c.category      AS company_category,
    COALESCE(p.name, '')  AS product_name,
    b.id            AS bullet_id,
    b.text          AS bullet_text,
    b.active        AS active
FROM bullets b
JOIN bullet_companies c ON c.id = b.company_id
LEFT JOIN bullet_products p ON p.id = b.product_id;

-- Job.json, one row per job.
CREATE VIEW v_job_document AS
SELECT
    j.id,
    j.job_description        AS jobDescription,
    j.tech_skills_json       AS techSkillsExtracted,
    j.bullets_extracted_json AS bulletsExtracted,
    j.resume_pdf_path        AS generatedPdf,
    j.status                 AS status
FROM job_applications j;

-- Can the library satisfy the FAANG + startup requirement right now?
-- Selection needs at least one active company in each slot category that
-- actually has active bullets; querying this up front gives a clear error
-- instead of an empty resume section.
CREATE VIEW v_selection_eligibility AS
SELECT
    c.category,
    COUNT(DISTINCT c.id)  AS eligible_companies,
    COUNT(b.id)           AS available_bullets
FROM bullet_companies c
LEFT JOIN bullets b ON b.company_id = c.id AND b.active = 1
WHERE c.active = 1
  AND c.category IN ('faang', 'startup')
GROUP BY c.category;

-- The final bullets for a job, in render order, with their company.
CREATE VIEW v_job_selected_bullets AS
SELECT
    s.job_application_id,
    s.role_slot,
    s.position,
    s.score,
    c.name AS company_name,
    COALESCE(p.name, '') AS product_name,
    b.text AS bullet_text
FROM job_selected_bullets s
JOIN bullets b            ON b.id = s.bullet_id
JOIN bullet_companies c   ON c.id = b.company_id
LEFT JOIN bullet_products p ON p.id = b.product_id
ORDER BY s.job_application_id, s.role_slot, s.position;
