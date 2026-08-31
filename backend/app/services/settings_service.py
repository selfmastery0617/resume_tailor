"""Application settings.

Three scopes exist in the schema; two are used today. Most settings belong to
the account, but anything tied to one resume identity is stored against the
profile — `firstCompany` names a company from that profile's own corpus, so a
single account-wide value would be validated against the wrong history.

Prompts live in their own table keyed by kind. The API still presents them as
ordinary settings keys, so nothing above this module has to care.
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import get_db
from app.models import prompts, settings

# New pipeline architecture, step 1: parses the raw job description into a
# structured requirements object (JSON) -- skills, responsibilities, system
# types, leadership expectations, business outcomes, ATS keywords, and a
# weighted matching-priority list -- for downstream semantic retrieval,
# resume generation, coverage analysis, and job-match scoring to consume.
# {job_description} is substituted via render_template (a plain string
# replace, not str.format), since the prompt's own JSON schema example is
# full of literal braces that str.format would choke on. See
# _extract_job_requirements in experience_service.py -- as of this build,
# the pipeline stops right after this step to verify its output before the
# rest of the architecture is built on top of it.
DEFAULT_REQUIREMENTS_PROMPT = """You are a Job Description Requirements Analyzer for an automated resume-tailoring system.

Your task is to parse the provided job description into a precise, structured requirements object that will be used by downstream systems for semantic retrieval, resume generation, coverage analysis, and job-match scoring.

IMPORTANT:

* Analyze only the job description provided.
* Do not use or infer anything about a candidate's experience.
* Do not generate resume content.
* Do not invent requirements that are not stated or reasonably implied by the job description.
* Preserve important technologies, responsibilities, domain terminology, and business objectives from the job description.
* Normalize obvious variations of technology names to standard industry terminology while preserving their intended meaning.
* Separate explicit requirements from preferred/nice-to-have qualifications.
* Break broad responsibilities into atomic requirements whenever possible.
* Avoid duplicate or substantially overlapping items.
* Make each responsibility independently meaningful because each item may later be used as a separate vector-search query.
* Return valid JSON only. Do not include markdown, explanations, comments, or text outside the JSON object.

Extraction Rules:

1. job_title
   Extract the exact or clearly intended job title.

2. seniority
   Determine the intended seniority level from the title and responsibilities.
   Use one of:
   Intern
   Entry
   Junior
   Mid
   Senior
   Lead
   Staff
   Principal
   Manager
   Director
   Executive
   Unknown

Do not infer a higher level merely because the role has ownership responsibilities.

3. mission
   Write exactly two complete sentences describing:

* what this role is fundamentally expected to accomplish;
* the business, customer, product, or organizational value of that work.

Do not list technologies in the mission unless the technology itself is fundamental to the role.

4. industry
   Identify the primary industry/domain of the employer or role using a concise standardized value such as:
   Technology
   Healthcare
   Finance
   Education
   Retail
   Advertising
   Media
   Manufacturing
   Automotive
   Transportation
   Real Estate
   Travel
   Hospitality
   Defense
   Government
   Pharmaceutical
   Biotechnology
   Sports
   Other

5. domain_keywords
   Extract important domain-specific concepts, terminology, business processes, datasets, regulations, or product areas relevant to the role.

Examples:
healthcare claims
advertising measurement
fraud detection
financial transactions
student learning analytics
supply chain
clinical data

Do not include generic technologies here.

6. must_have_skills
   Extract technical skills, tools, languages, frameworks, platforms, methodologies, and professional competencies that the job description explicitly requires or clearly treats as fundamental.

Each item must contain:

* name: normalized skill name
* importance: "critical" or "high"
* evidence: a short phrase describing why it is considered required

Use "critical" when the JD explicitly requires, emphasizes, or repeatedly references the skill.
Use "high" for clearly important core skills that are not absolute requirements.

7. preferred_skills
   Extract technologies, tools, capabilities, or experience described as preferred, desirable, nice-to-have, bonus, advantageous, or equivalent.

Each item must contain:

* name
* importance: "medium" or "low"
* evidence

8. core_responsibilities
   Convert the role's responsibilities into atomic, concise statements.

GOOD:
"Design scalable batch and streaming data pipelines."
"Improve production data quality and pipeline reliability."
"Partner with product teams to define analytics requirements."

BAD:
"Build pipelines, improve quality, work with stakeholders, and support analytics."

Each responsibility must represent primarily one responsibility or closely related objective.

Each item must contain:

* id: sequential IDs such as "R1", "R2", "R3"
* requirement
* importance: "critical", "high", "medium", or "low"
* category

Use one of these categories where applicable:
architecture
development
data_engineering
distributed_systems
cloud
infrastructure
reliability
performance
security
data_quality
governance
analytics
machine_learning
integration
operations
collaboration
leadership
mentoring
business
other

9. system_types
   Extract the types of systems, platforms, products, or workloads the person is expected to build, operate, improve, or support.

Examples:
batch data pipelines
real-time streaming platform
distributed data processing system
data warehouse
lakehouse
REST APIs
cloud infrastructure
analytics platform
ML infrastructure

Do not invent a system type merely from a listed technology.

10. leadership_requirements
    Extract expectations involving:

* technical leadership
* architecture ownership
* mentoring
* cross-functional leadership
* stakeholder communication
* roadmap influence
* standards/best practices
* project ownership

Return an empty array if none are present.

Each item must contain:

* requirement
* importance

11. business_outcomes
    Extract the outcomes the employer expects this role to influence.

Examples:
improve reliability
reduce infrastructure cost
accelerate analytics
increase developer productivity
support customer growth
improve data accessibility
reduce operational burden
improve security

Focus on outcomes rather than implementation details.

Each item must contain:

* outcome
* importance

12. ats_keywords
    Extract important exact or normalized phrases likely to matter when matching a resume to this job.

Include:

* major technical skills
* methodologies
* architectural concepts
* important domain terminology
* core responsibility phrases

Do not include generic filler such as:
team player
hard working
excellent company
fast-paced environment

Avoid duplicates with trivial wording differences.

13. requirement_summary
    Create a compact representation for downstream matching containing:

* top_technical_requirements: the 5-10 most important technical requirements
* top_functional_requirements: the 5-8 most important responsibilities
* top_business_requirements: the 3-5 most important expected outcomes
* differentiators: requirements that appear particularly distinctive for this role compared with a generic role of the same title

14. matching_priority
    Identify the requirements that should contribute most strongly to resume/job matching.

Return 5-12 items.

Each item must contain:

* requirement
* type: "skill", "responsibility", "domain", "leadership", "system_type", or "business_outcome"
* weight: integer from 1 to 10

Use:
9-10 = central/essential to the role
7-8 = highly important
5-6 = meaningful secondary requirement
1-4 = minor requirement

Do not assign 9 or 10 to everything.

Return exactly this JSON structure:

{
  "job_title": "",
  "seniority": "",
  "mission": "",
  "industry": "",
  "domain_keywords": [],
  "must_have_skills": [
    {
      "name": "",
      "importance": "",
      "evidence": ""
    }
  ],
  "preferred_skills": [
    {
      "name": "",
      "importance": "",
      "evidence": ""
    }
  ],
  "core_responsibilities": [
    {
      "id": "R1",
      "requirement": "",
      "importance": "",
      "category": ""
    }
  ],
  "system_types": [],
  "leadership_requirements": [
    {
      "requirement": "",
      "importance": ""
    }
  ],
  "business_outcomes": [
    {
      "outcome": "",
      "importance": ""
    }
  ],
  "ats_keywords": [],
  "requirement_summary": {
    "top_technical_requirements": [],
    "top_functional_requirements": [],
    "top_business_requirements": [],
    "differentiators": []
  },
  "matching_priority": [
    {
      "requirement": "",
      "type": "",
      "weight": 0
    }
  ]
}

Job Description:
{job_description}
"""

# New pipeline architecture, step 2: converts step 1's structured analysis
# (still in the same chat -- this prompt has no placeholders, it relies
# entirely on conversation context, per its own "do not ask me to provide
# the previous output again" instruction) into atomic matching requirements
# for downstream semantic retrieval, coverage-gap detection, synthetic
# experience generation, resume bullet planning, and job-match scoring. See
# _extract_matching_requirements in experience_service.py.
DEFAULT_MATCHING_REQUIREMENTS_PROMPT = """You are continuing the same resume-tailoring workflow from the previous step.

Use the structured job-description analysis you just generated in this conversation as the source for this step.

Your task is to convert that analysis into a precise set of atomic matching requirements that will later be used for:

* semantic/vector search against experience challenges;
* coverage-gap detection;
* synthetic experience generation;
* resume bullet planning;
* job-match scoring.

Do not re-analyze the original job description from scratch unless necessary to resolve ambiguity.
Do not ask me to provide the previous output again.
Use the information already available in this conversation.

IMPORTANT RULES:

1. Use only requirements supported by the job description and the structured analysis already generated.

2. Do not use or infer candidate experience.

3. Do not generate resume bullets or synthetic experience yet.

4. Break broad requirements into atomic, independently matchable requirements.

GOOD:
"Design scalable batch data pipelines."
"Build real-time streaming pipelines."
"Improve production data quality."
"Mentor engineers."

BAD:
"Design pipelines, improve data quality, and mentor engineers."

5. Separate responsibilities from technologies.

Example:

If the requirement is:
"Build scalable data pipelines using Spark and Airflow."

Create separate atomic requirements for:

* Build scalable data pipelines.
* Use Apache Spark for distributed data processing.
* Use Apache Airflow for workflow orchestration.

6. Separate technical implementation from business outcomes.

Example:

"Optimize pipelines to reduce cloud infrastructure costs."

Create:

* Optimize data-processing infrastructure.
* Reduce infrastructure or compute costs.

7. Separate leadership from technical execution.

Example:

"Lead architecture reviews and mentor junior engineers."

Create:

* Lead technical architecture reviews.
* Mentor engineers.

8. Avoid generic requirements unless they are specifically important to the role.

Generally exclude generic phrases such as:

* strong communication skills
* problem solving
* team player
* fast-paced environment
* attention to detail

Include collaboration when it represents meaningful work, such as:

* partner with product teams to define requirements;
* collaborate with analytics teams;
* communicate architectural decisions;
* present recommendations to leadership.

9. Requirement Types

Assign exactly one type to each requirement:

technical_skill
responsibility
system_type
domain
leadership
business_outcome
methodology

10. Importance

Assign one of:

critical
high
medium
low

Definitions:

critical:
Explicitly mandatory, repeatedly emphasized, or fundamental to the role.

high:
Central to successfully performing the role.

medium:
Useful, preferred, or differentiating.

low:
Minor or secondary preference.

Do not classify nearly everything as critical.

10b. Retrieval Eligibility

Assign retrieval_eligible as true or false.

Set it to false for requirements that describe eligibility, credentials, or logistics rather than demonstrable engineering work -- these cannot be matched against experience challenges and should never be searched against database.json:

years-of-experience thresholds (e.g. "5+ years of experience")
degree or certification requirements
work authorization or visa requirements
location, relocation, or on-site requirements
language fluency requirements
security clearance requirements

Set it to true for everything else -- responsibilities, technical skills, system types, domain work, leadership, and business outcomes -- anything a real challenge or project could actually demonstrate.

Examples:

"Build ETL pipelines." → true
"Perform data reconciliation." → true
"Use Python." → true
"Mentor engineers." → true
"5+ years of experience." → false
"Bachelor's degree in Computer Science." → false
"Must be authorized to work in the US." → false
"On-site in Austin, TX." → false

11. Generation Priority

Assign generation_priority from 1 to 10.

10:
The resume would seriously fail to represent the target role if this requirement were missing.

8-9:
Very important and should strongly influence project/challenge selection or generation.

6-7:
Meaningful secondary coverage.

4-5:
Preferred or differentiating requirement.

1-3:
Minor requirement.

12. Preferred Resume Surface

For each requirement, indicate where it should ideally appear:

experience
skills
both
summary

Use:

experience:
Responsibilities, architecture, leadership, outcomes, ownership, collaboration.

both:
Important technical skills that should appear in actual work context and in the skills section.

skills:
Secondary tools or technologies that do not require a dedicated bullet.

summary:
Only major specialization or role-defining concepts.

Do not use the professional summary as a keyword dump.

13. Coverage Groups

Assign each requirement to a concise logical coverage group.

Examples:

data_pipeline_architecture
streaming
batch_processing
data_quality
data_governance
cloud_infrastructure
analytics
distributed_systems
performance
reliability
security
stakeholder_collaboration
leadership
mentoring

Requirements remain atomic even when they belong to the same group.

14. Semantic Search Query

For every requirement, generate one semantic_search_query that will later be embedded using SentenceTransformer.

The semantic_search_query should describe the type of engineering challenge, responsibility, or outcome that would demonstrate this requirement.

It should be written as natural semantic text rather than a keyword list.

Example:

Requirement:
"Improve production data quality."

Semantic search query:
"Built or improved production data systems that detected, prevented, or remediated data-quality issues and increased the reliability of downstream datasets."

Example:

Requirement:
"Build scalable streaming pipelines."

Semantic search query:
"Designed or implemented high-throughput real-time data pipelines that ingest, process, and deliver streaming events at scale."

Example:

Requirement:
"Use Apache Kafka."

Semantic search query:
"Built event-driven or real-time data-processing systems using Apache Kafka for distributed messaging, event ingestion, or stream processing."

For technology requirements:

* preserve the exact technology name in the requirement;
* describe its realistic engineering use case in the semantic search query.

Do not put years, dates, or timeline language into semantic_search_query -- that field is pure semantic text about the type of work, not about when it happened. Timeline information belongs only in earliest_plausible_year below.

14b. Technology Timeline Metadata

For every requirement whose type is a specific named technology, tool, platform, or framework (not a general methodology or responsibility), also identify:

technology: the normalized technology name, matching how it appears in the requirement itself.

earliest_plausible_year: the earliest calendar year this technology could realistically have been used in production, based on its public release or widespread industry adoption (e.g. Apache Spark: 2014, Apache Kafka: 2011, Snowflake: 2015, Apache Airflow: 2015, dbt: 2018, Kubernetes: 2015). Use your own knowledge of when the technology became available -- do not guess wildly, and prefer the more conservative (earlier) year when genuinely uncertain between two plausible years.

timeline_confidence: "high", "medium", or "low", reflecting how confident you are in earliest_plausible_year.

For every requirement that is NOT a specific named technology (a responsibility, methodology, domain, leadership, or business-outcome requirement), set all three to null:

technology: null
earliest_plausible_year: null
timeline_confidence: null

This is separate from semantic_search_query and answers a different question: earliest_plausible_year checks whether a JD technology is even possible for a given product's own timeline; semantic_search_query checks whether a database challenge represents relevant experience.

15. Search Intent

For each requirement, assign search_intent as one of:

challenge
action
business_impact
seniority
project_context
technology_context

Use the value representing the part of the experience database most useful for finding a relevant grounding challenge.

Examples:

"Improve pipeline reliability"
→ challenge

"Architect scalable data pipelines"
→ action

"Reduce infrastructure cost"
→ business_impact

"Mentor engineers"
→ seniority

"Build healthcare analytics infrastructure"
→ project_context

"Use Apache Spark"
→ technology_context

16. Retrieval Priority

Assign retrieval_priority from 1 to 10.

This indicates how important it is to search database.json for an existing relevant challenge before generating a new synthetic experience.

High retrieval priority:

* core responsibilities;
* system architecture;
* major business outcomes;
* domain-specific work.

Lower retrieval priority:

* simple individual technology keywords that can naturally be incorporated into a broader generated project.

17. Synthetic Generation Priority

Assign synthetic_generation_priority from 1 to 10.

This indicates how important it would be to create new synthetic experience if database retrieval does not adequately cover this requirement.

High values should be given to:

* central JD responsibilities;
* role-defining architectures;
* important business outcomes;
* critical leadership expectations;
* distinctive requirements.

Do not give every requirement a high value.

18. Deduplication

Before producing the result:

* remove exact duplicates;
* merge semantically equivalent requirements;
* retain the stronger importance and priority values;
* do not merge requirements that are independently meaningful.

Example:

"Build high-scale data pipelines."
"Develop scalable data pipelines."

→ merge.

But:

"Build batch pipelines."
"Build streaming pipelines."

→ keep separate when both matter to the JD.

19. Requirement IDs

Assign sequential IDs:

REQ-001
REQ-002
REQ-003
...

Order requirements approximately by:

1. Critical responsibilities

2. Critical system/architecture requirements

3. Critical technical skills

4. High-priority responsibilities

5. Leadership and collaboration

6. Business outcomes

7. Preferred technologies and secondary requirements

8. Coverage Groups

After generating all requirements, create coverage_groups that show which requirements can naturally be demonstrated together within the same project.

For example:

{
"name": "streaming_platform",
"requirement_ids": [
"REQ-002",
"REQ-005",
"REQ-008"
],
"group_priority": 9
}

This does NOT mean those requirements should be merged. It means they could later be addressed by one coherent project or experience.

21. Critical Requirement List

Create critical_requirement_ids containing the requirements that absolutely should be covered by the finished resume.

22. High-Priority Requirement List

Create high_priority_requirement_ids containing both critical and highly important requirements that should drive retrieval, generation, and final match scoring.

Return valid JSON only.

Do not include markdown.
Do not include commentary.
Do not repeat the job description.
Do not generate resume content.

Return exactly this structure:

{
"target_role": {
"job_title": "",
"seniority": "",
"industry": "",
"mission": ""
},
"requirements": [
{
"id": "REQ-001",
"requirement": "",
"type": "",
"importance": "",
"generation_priority": 0,
"technology": null,
"earliest_plausible_year": null,
"timeline_confidence": null,
"retrieval_eligible": true,
"retrieval_priority": 0,
"synthetic_generation_priority": 0,
"coverage_group": "",
"preferred_resume_surface": "",
"search_intent": "",
"semantic_search_query": ""
}
],
"coverage_groups": [
{
"name": "",
"requirement_ids": [],
"group_priority": 0
}
],
"critical_requirement_ids": [],
"high_priority_requirement_ids": []
}
"""

# New pipeline architecture, step 4: chooses exactly one Company 2 from step
# 3's shortlist, selects which retrieved challenges from each company
# actually ground the resume, and classifies per-requirement coverage
# (strong/partial/uncovered) plus gap-detection for a later generation
# step. Step 3's own output (Company 1's candidate challenges, the Company
# 2 shortlist) was never sent to ChatGPT -- it's pure Python/sentence-
# transformers, computed entirely outside the chat -- so despite this
# prompt's own "use the outputs already generated in this session" framing,
# _build_selection_message in experience_service.py includes that data in
# the message explicitly; this constant is only the instructions half.
DEFAULT_SELECTION_PROMPT = """You are continuing the same resume-tailoring workflow from Steps 1-3 in this conversation.

Use the outputs already generated in this session. Do not ask me to provide previous outputs again.

TASK

Build the final experience-grounding plan for exactly two resume companies.

Company 1:

* Fixed by the user before this step.
* Keep the Company 1 company/product selected in Step 3.
* Keep all Company 1 challenges returned in Step 3.
* Do not replace Company 1.

Company 2:

* Select exactly ONE company/product from the Company 2 shortlist produced in Step 3.
* Do not introduce a company or product outside that shortlist.

GOAL

Choose Company 2 so Company 1 + Company 2 together provide the strongest coverage of the target job description.

Do NOT select Company 2 only by highest raw similarity score.

Prefer the Company 2 candidate that adds important requirements Company 1 covers weakly or does not cover.

SELECTION PRIORITY

Prioritize:

1. critical JD requirements;
2. high-priority JD requirements;
3. must-have technical skills;
4. core responsibilities;
5. relevant domain/industry experience;
6. system/platform experience;
7. leadership and seniority requirements;
8. important business outcomes;
9. complementary coverage instead of duplicate experience.

COMPANY 1 RULES

Company 1 is fixed and represents the earlier role.

Use all Company 1 challenges returned by Step 3 as grounding evidence.

Evaluate what Company 1 covers:

* strongly;
* partially;
* not at all.

Do not force requirements into Company 1 when they do not naturally fit its product, domain, level, or timeline.

COMPANY 2 RULES

Company 2 is selected dynamically from the Step 3 shortlist and represents the later senior-level role.

Choose the candidate that best fills Company 1 coverage gaps while remaining strongly relevant to the target JD.

Use only challenges retrieved from the selected company/product.

Prefer challenges that provide:

* direct evidence for critical requirements;
* domain-specific evidence;
* strong technical relevance;
* senior-level ownership;
* measurable impact;
* complementary experience.

Do not create synthetic challenges yet.

REQUIREMENT COVERAGE

For every important Step 2 requirement where `retrieval_eligible = true`, classify combined coverage as:

* `strong`
* `partial`
* `uncovered`

`strong`:
Direct or very close retrieved evidence exists.

`partial`:
Related evidence exists but does not fully demonstrate the requirement.

`uncovered`:
Neither company provides sufficient evidence.

Do not classify a requirement as strong only because cosine similarity is non-zero.

TIMELINE RULE

Respect technology timeline information from Step 2 and product timelines from Step 3.

Do not credit a timeline-sensitive technology to a company if it is incompatible with that company's timeline.

Requirements with no applicable timeline may be evaluated normally.

COMPLEMENTARY COVERAGE

Avoid unnecessary duplication.

If Company 1 already strongly covers a requirement, prefer Company 2 candidates that contribute different high-value requirements.

A challenge may support multiple closely related requirements, but do not exaggerate its coverage.

SOURCE PRESERVATION

Do not change facts or metrics from `database.json`.

Do not create:

* new challenges;
* new projects;
* new technologies;
* new metrics;
* resume bullets.

This step is selection, coverage analysis, and gap detection only.

GAP DETECTION

For each important requirement classified as `partial` or `uncovered`, decide whether it should become a generation target for the next step.

Use:

* importance;
* generation_priority;
* synthetic_generation_priority.

Recommend the most appropriate future role:

* `company_1`
* `company_2`
* `either`

Use `company_1` only when the requirement realistically fits Company 1's product, level, domain, and timeline.

Use `company_2` when it fits the selected later senior-level role more naturally.

Do not include requirements where `retrieval_eligible = false`.

OUTPUT

Return valid JSON only:

{
"company_1": {
"company": "",
"product": "",
"timeline": "",
"selection_type": "fixed",
"selected_challenges": [
{
"challenge_id": "",
"primary_requirement_ids": [],
"secondary_requirement_ids": []
}
]
},
"company_2": {
"company": "",
"product": "",
"timeline": "",
"selection_type": "dynamic",
"selection_reason": "",
"complementary_requirement_ids": [],
"selected_challenges": [
{
"challenge_id": "",
"primary_requirement_ids": [],
"secondary_requirement_ids": []
}
]
},
"combined_coverage": [
{
"requirement_id": "",
"coverage": "strong",
"covered_by": [],
"evidence_challenge_ids": []
}
],
"remaining_gaps": [
{
"requirement_id": "",
"coverage": "partial",
"importance": "",
"synthetic_generation_priority": 0,
"reason": "",
"recommended_role": "company_2"
}
],
"generation_targets": [
{
"requirement_id": "",
"recommended_role": "",
"reason": ""
}
]
}

OUTPUT RULES

* JSON only.
* Company 1 must remain the user-selected fixed company.
* Keep all Company 1 challenges returned in Step 3.
* Select exactly one Company 2.
* Do not generate synthetic experience yet.
* Do not generate resume bullets.
* Do not alter source metrics.
* Do not add requirement IDs that do not exist in Step 2.
* Do not include `retrieval_eligible = false` requirements in gaps or generation targets.
* Optimize for combined JD coverage.
"""

# New pipeline architecture, step 5: generates structured synthetic
# experience ONLY for the gaps/generation_targets step 4's own reply
# identified -- a pure conversation follow-up, no placeholders and no data
# re-injected: unlike step 3 (pure Python, never sent to ChatGPT), step 4
# ran IN this chat, so its JSON grounding plan (and the retrieved
# challenges it was built from) is already in the model's own context. See
# _generate_synthetic_experience in experience_service.py.
DEFAULT_SYNTHETIC_GENERATION_PROMPT = """You are continuing the same resume-tailoring workflow from the previous steps in this conversation.

Use all outputs already generated in this session. Do not ask me to provide previous outputs again.

TASK

Generate structured synthetic experience ONLY for the remaining gaps and generation targets identified in the previous step.

Do not generate resume bullets yet.

The goal is to fill important missing JD coverage while keeping the experience coherent with the two already-selected resume companies.

COMPANY RULES

There are exactly two resume companies:

* `company_1`: fixed by the user and already established in the previous step.
* `company_2`: dynamically selected in the previous step.

Use the company, product, timeline, industry, role level, and existing retrieved challenges already established for each company.

Do not replace either company.

GENERATION RULE #1: GENERATE ONLY FOR REAL GAPS

Use only the `generation_targets` identified in the previous step.

Do not generate new experience for requirements already classified as `strong`.

Prioritize:

1. critical uncovered requirements;
2. critical partial requirements;
3. high-priority uncovered requirements;
4. high-priority partial requirements;
5. remaining useful differentiators.

Do not generate for requirements where `retrieval_eligible = false`.

GENERATION RULE #2: FOLLOW RECOMMENDED ROLE

Use the `recommended_role` from the previous step.

If `company_1`:

* the generated experience must fit Company 1's product, industry, timeline, and level.

If `company_2`:

* the generated experience must fit Company 2's product, industry, timeline, and level.

If `either`:

* choose the company where the experience is most natural and creates the strongest overall resume.

Do not force a domain-specific requirement into an unrelated company.

GENERATION RULE #3: TIMELINE ACCURACY

Respect all technology timeline information already established in the previous steps and the product timelines already selected for both companies.

Every named technology, framework, service, protocol, platform feature, or branded capability must have been realistically available during that company's timeline.

Do not use modern technologies or modern product branding in historical experience.

If a target JD technology is incompatible with the company's timeline, do not use it in that company.

GENERATION RULE #4: PRODUCT AND DOMAIN REALISM

Generated experience must be realistic for:

* the selected company;
* its product;
* its industry;
* its business model;
* its engineering environment;
* its role level.

Do not simply copy the wording of the target JD.

Translate the JD requirement into a realistic project/challenge that could naturally exist within that company's product environment.

GENERATION RULE #5: EXTEND EXISTING EXPERIENCE

Whenever possible, generate a new challenge that fits naturally into one of the existing projects already associated with that company.

Create a new project only when the missing requirements cannot reasonably fit an existing project.

Do not rewrite or modify retrieved database challenges.

Synthetic challenges should complement retrieved challenges rather than duplicate them.

GENERATION RULE #6: COVER MULTIPLE RELATED GAPS

A single generated challenge may cover multiple closely related requirement IDs.

Prefer one coherent challenge covering several related gaps instead of generating one challenge per requirement.

For example:

Data migration + validation + reconciliation + automation

may be represented by one strong migration-quality challenge if they logically belong together.

Do not combine unrelated requirements merely to maximize keyword coverage.

GENERATION RULE #7: SENIORITY

Company 1:
Follow the level already assigned to Company 1.

Earlier/mid-level roles should emphasize:

* hands-on implementation;
* scoped ownership;
* debugging;
* optimization;
* collaboration;
* delivery.

Company 2:
Follow the senior-level scope already established.

Later/senior roles may emphasize:

* architecture;
* technical leadership;
* cross-team coordination;
* standards;
* mentoring;
* complex migrations or platform initiatives;
* business/domain ownership.

Do not make every senior challenge a people-management story.

GENERATION RULE #8: METRICS

Generate realistic quantitative evidence for each synthetic challenge.

Use approximately 1-3 meaningful metrics where appropriate.

Possible metrics include:

* runtime reduction;
* throughput improvement;
* reliability;
* error reduction;
* validation accuracy;
* incident reduction;
* manual effort reduction;
* cost reduction;
* data volume;
* number of pipelines;
* number of systems;
* number of customers;
* migration duration;
* processing scale.

Metrics must be realistic for the company/product.

Do not exaggerate scale.

Do not force dollar savings into every challenge.

CRITICAL: Metrics generated in this step become IMMUTABLE SOURCE FACTS for later steps.

Later resume-bullet generation must preserve these metrics exactly.

GENERATION RULE #9: NO DUPLICATE STORIES

Compare generated challenges against all retrieved challenges from both companies.

Do not generate substantially identical:

* problems;
* actions;
* technologies;
* outcomes;
* metrics.

Each generated challenge should contribute new JD coverage.

GENERATION RULE #10: REQUIREMENT TRACEABILITY

Every generated challenge must explicitly list the existing requirement IDs it is intended to cover.

Use only valid requirement IDs already generated earlier in the workflow.

Separate them into:

* `primary_requirement_ids`
* `secondary_requirement_ids`

Primary requirements are the main reason the challenge exists.

Secondary requirements are naturally supported but are not the main focus.

GENERATION RULE #11: ONE SENTENCE PER EXPERIENCE FIELD

Each of these fields must contain exactly one complete sentence:

* challenge
* action
* achievement
* business_impact
* seniority_indicator

Keep them specific, concise, and information-dense.

GENERATION RULE #12: DO NOT GENERATE RESUME CONTENT YET

Do not create:

* resume bullets;
* professional summary;
* skills section;
* resume title;
* company summary;
* keyword markers.

This step creates structured source experience only.

OUTPUT

Return valid JSON only:

{
"company_1": {
"company": "",
"product": "",
"timeline": "",
"generated_experience": [
{
"project": "",
"project_type": "existing",
"primary_requirement_ids": [],
"secondary_requirement_ids": [],
"challenge": "",
"action": "",
"achievement": "",
"business_impact": "",
"seniority_indicator": ""
}
]
},
"company_2": {
"company": "",
"product": "",
"timeline": "",
"generated_experience": [
{
"project": "",
"project_type": "existing",
"primary_requirement_ids": [],
"secondary_requirement_ids": [],
"challenge": "",
"action": "",
"achievement": "",
"business_impact": "",
"seniority_indicator": ""
}
]
},
"coverage_after_generation": [
{
"requirement_id": "",
"coverage": "strong",
"covered_by": [
"retrieved",
"synthetic"
]
}
],
"remaining_uncovered_requirements": []
}

OUTPUT RULES

* Output JSON only.
* Generate only from generation targets identified in the previous step.
* Do not replace either company.
* Do not modify retrieved challenges.
* Do not generate resume bullets.
* Do not invent requirement IDs.
* Respect company/product timelines.
* Preserve realistic role seniority.
* Avoid duplicate experience.
* Freeze all generated metrics as immutable facts for later steps.
* If no synthetic experience is needed for a company, return an empty `generated_experience` array.
* If all important requirements are covered after generation, return an empty `remaining_uncovered_requirements` array.
"""

DEFAULT_BULLETS_PROMPT = """You are continuing the same resume-tailoring workflow from the previous steps in this conversation.

Use all outputs already generated in this session. Do not ask me to provide previous outputs again.

TASK

Generate the final resume experience bullets for the two selected resume companies.

Use ONLY:
* selected retrieved challenges from the final Company 1;
* selected retrieved challenges from the final Company 2;
* synthetic challenges generated in the previous step;
* JD requirements and coverage information already established.

Do not create any new experience, metrics, projects, technologies, or facts.

BULLET COUNT

Generate:
* exactly 6 resume bullets for Company 1;
* exactly 8 resume bullets for Company 2.

Company 1 is the earlier role.

Company 2 is the later role and receives more bullets because it should carry more of the target-role-specific, senior-level, domain-specific, and gap-filling experience.

SOURCE-OF-TRUTH RULE

Every bullet must be grounded in at least one retrieved or synthetic challenge already established in the workflow.

You may combine closely related source challenges into one bullet when they describe a coherent piece of work.

Do NOT invent:
* new metrics;
* new technologies;
* new responsibilities;
* new business impact;
* new team sizes;
* new scale;
* new project facts.

All existing metrics are immutable.

If a source says `47%`, the bullet must use exactly `47%`.

Do not round, modify, combine, extrapolate, or manufacture metrics.

JD COVERAGE PRIORITY

Use the 14 bullets across both companies to maximize coverage of the important target-job requirements.

Prioritize:
1. critical requirements;
2. high-priority requirements;
3. must-have technologies;
4. core responsibilities;
5. domain-specific requirements;
6. leadership/seniority;
7. important business outcomes.

Requirements already strongly represented do not need excessive repetition.

Prefer complementary bullets that collectively cover different high-value requirements.

COMPANY 1

Company 1 is the earlier role and must contain exactly 6 bullets.

Its bullets should emphasize the role level already established for Company 1, such as:
* hands-on implementation;
* engineering ownership;
* pipeline development;
* optimization;
* reliability;
* debugging;
* testing;
* technical collaboration.

Do not artificially make every Company 1 bullet senior-level.

COMPANY 2

Company 2 is the later role and must contain exactly 8 bullets.

Use the additional Company 2 bullet capacity to emphasize requirements that are especially important to the target JD, including where supported:
* domain-specific experience;
* architecture;
* migration/integration;
* technical ownership;
* cross-functional coordination;
* reusable standards;
* automation;
* complex initiatives;
* business outcomes;
* mentoring or leadership.

Company 2 should demonstrate an appropriate mix of hands-on technical work and broader senior-level ownership.

Do NOT force leadership into every bullet.

Approximately 3-4 of the 8 Company 2 bullets should clearly demonstrate senior-level leadership, architecture ownership, standards, or cross-functional responsibility when supported by the source experience.

BULLET STRUCTURE

Each bullet should:
1. start with a strong past-tense action verb;
2. clearly explain what system/project/process was being worked on;
3. explain the important technical action;
4. naturally include relevant technologies or domain terminology;
5. end with measurable technical or business impact when available.

Preferred structure:

`Action + system/function + technical implementation + measurable result/business impact`

CONTEXTUAL CLARITY

The first half of every bullet must clearly explain what the system or project actually does.

Avoid vague internal wording.

Bad:

`Optimized migration pipelines.`

Better:

`Optimized clinical-data migration pipelines transferring legacy patient records into the target EHR platform...`

A recruiter should understand the purpose of the work without knowing internal project terminology.

JD KEYWORD ALIGNMENT

Naturally use exact or close JD terminology when supported by the source experience.

This may include:
* technologies;
* methodologies;
* system types;
* domain terminology;
* responsibilities;
* business outcomes.

Do not keyword-stuff.

Do not insert a JD technology unless it is supported by the source experience and compatible with that company's timeline.

TIMELINE ACCURACY

Respect the company/product timelines already established.

Do not introduce technologies, services, standards, features, or modern product branding that were not realistically available during that role.

Do not modify historically correct technology terminology from the source experience.

PROJECT DISTRIBUTION

Do NOT force equal bullet distribution across projects.

Allocate bullets based on:
* JD relevance;
* strength of evidence;
* requirement coverage;
* impact;
* seniority value.

Company 2 may allocate more bullets to projects and synthetic experiences that directly address important target-job requirements.

Avoid making all bullets minor variations of the same project when useful evidence exists across multiple projects.

DIVERSITY

Across each company's bullets, avoid repetitive stories.

Where supported, include a useful mix of:
* architecture/implementation;
* migration/integration;
* data quality;
* reliability;
* performance;
* automation;
* governance/standards;
* stakeholder coordination;
* business impact.

Do not repeat the same metric or accomplishment across multiple bullets.

SYNTHETIC EXPERIENCE

Synthetic challenges generated in the previous step are now valid source experience.

Treat their facts and metrics exactly like retrieved challenge facts.

Do not label any resume bullet as synthetic.

Do not distinguish retrieved versus synthetic experience in the bullet wording.

CONCISENESS

Each bullet must be one sentence.

Keep bullets concise, information-dense, and recruiter-readable.

Target approximately 25-40 words per bullet when possible.

Avoid:
* excessive clauses;
* filler;
* vague adjectives;
* repeated technology lists;
* unnecessary internal jargon.

REQUIREMENT TRACEABILITY

For internal workflow purposes, associate each bullet with the most important requirement IDs it supports.

Use:
* `primary_requirement_ids`
* `secondary_requirement_ids`

Do not assign requirement IDs that the bullet does not meaningfully demonstrate.

FINAL VALIDATION

Before returning the output, verify:
1. Company 1 contains exactly 6 bullets.
2. Company 2 contains exactly 8 bullets.
3. There are exactly 14 bullets total.
4. Every bullet is grounded in existing retrieved or synthetic experience.
5. No new facts or metrics were invented.
6. Every numeric value exactly matches its source.
7. No metric is altered or rounded.
8. No timeline-incompatible technology is introduced.
9. Important JD requirements receive strong overall coverage.
10. Bullets are not unnecessarily repetitive.
11. Company 1 reflects its established role level.
12. Company 2 reflects appropriate senior-level scope.
13. Leadership is demonstrated selectively, not forced into every bullet.
14. Each bullet starts with a strong past-tense action verb.
15. Each bullet clearly communicates system/project purpose.
16. No bullet contains unsupported JD keyword stuffing.
17. The extra Company 2 bullets contribute useful JD coverage rather than repeating existing accomplishments.

OUTPUT

Return valid JSON only:

{
"company_1": {
"company": "",
"product": "",
"timeline": "",
"bullets": [
{
"bullet": "",
"source_challenge_ids": [],
"primary_requirement_ids": [],
"secondary_requirement_ids": []
}
]
},
"company_2": {
"company": "",
"product": "",
"timeline": "",
"bullets": [
{
"bullet": "",
"source_challenge_ids": [],
"primary_requirement_ids": [],
"secondary_requirement_ids": []
}
]
}
}

OUTPUT RULES

* JSON only.
* Exactly 6 bullets for Company 1.
* Exactly 8 bullets for Company 2.
* Exactly 14 bullets total.
* Use only previously established retrieved and synthetic experience.
* Preserve every source metric exactly.
* Do not invent facts.
* Do not invent technologies.
* Do not generate new synthetic experience.
* Do not modify company/product timelines.
* Do not generate professional summary, skills, title, or company summaries yet.
"""

DEFAULT_RESUME_CONTENT_PROMPT = """You are continuing the same resume-tailoring workflow from the previous steps in this conversation.

Use all outputs already generated in this session. Do not ask me to provide previous outputs again.

TASK

Using the finalized Job Description analysis, requirement coverage, selected companies, established role levels, and final Step 6 experience bullets, generate the remaining resume content:
1. overall resume title;
2. professional summary;
3. skills section;
4. role title for Company 1;
5. role title for Company 2;
6. company summaries.

Do NOT rewrite, regenerate, reorder, shorten, expand, or otherwise modify the experience bullets created in Step 6.

The Step 6 bullets are final source content.

SOURCE-OF-TRUTH RULE

Use ONLY information already established in this workflow, including:
* Job Description requirements;
* finalized Company 1 and Company 2;
* company products and timelines;
* established role levels;
* retrieved experience;
* synthetic experience;
* finalized Step 6 bullets;
* technologies and domain terminology already supported by those sources.

Do NOT invent:
* new technologies;
* new domains;
* new responsibilities;
* new certifications;
* new years of experience;
* new leadership claims;
* new business impact;
* new metrics;
* new tools;
* new qualifications.

STEP 6 PRESERVATION RULE

The Step 6 experience bullets are immutable.

Return them exactly as generated in the previous step.

Company 1 must retain exactly 6 bullets.

Company 2 must retain exactly 8 bullets.

Do not change:
* wording;
* ordering;
* metrics;
* technologies;
* facts.

OVERALL RESUME TITLE

Generate one concise `resume_title` aligned with the target role.

Rules:
* Prefer the target job title or a close normalized equivalent.
* Optimize the title for target-role relevance.
* Keep it concise.
* Do not add unsupported seniority.
* Do not keyword-stuff the title.

The overall resume title is target-facing and is separate from the role titles held at each company.

COMPANY ROLE TITLES

Generate one `title` for each company.

The company role title must represent the role performed at that specific company.

If an exact role title was already established earlier in the workflow, preserve it.

If only a role level was established, generate a conservative normalized title consistent with:
* company role level;
* timeline;
* responsibilities;
* technologies;
* scope of ownership;
* established experience.

Do NOT simply copy the target JD title into both companies.

Do NOT upgrade a company's seniority merely to better match the JD.

Do NOT introduce a domain-specific title unless the company experience actually supports that domain.

Company 1 is the earlier role.

Its title should reflect the established Company 1 role level and scope.

Company 2 is the later role.

Its title should reflect the established Company 2 role level and broader scope where supported.

Examples of appropriate normalization when supported:
* Data Engineer
* Software Engineer
* Senior Data Engineer
* Senior Software Engineer
* Integration Engineer
* Senior Integration Engineer

These are examples only.

Choose the title that best matches the established evidence.

ROLE-TITLE CONSISTENCY

The role title must be consistent with the bullets underneath it.

For example:
* a `Senior` title requires senior-level scope already established in the experience;
* an `Integration Engineer` title should be supported by meaningful integration work;
* a `Data Engineer` title should be supported by substantial data-engineering responsibilities.

Do not use a title merely because it appears in the target JD.

PROFESSIONAL SUMMARY

Generate a concise professional summary of approximately 3-4 sentences.

The summary should:
* align strongly with the target job;
* highlight the most important technical strengths;
* mention relevant domain expertise when supported;
* reflect the strongest responsibilities demonstrated across both companies;
* include important JD terminology naturally;
* communicate appropriate overall seniority;
* emphasize relevant systems, architecture, migration, integration, reliability, automation, or leadership where supported.

Do NOT:
* introduce new facts;
* invent years of experience;
* invent team sizes;
* invent certifications;
* invent business metrics;
* claim expertise unsupported by established experience;
* copy individual bullets verbatim.

The summary should synthesize the evidence rather than repeat bullet wording.

SKILLS SECTION

Generate a structured skills section using only technologies, tools, methodologies, platforms, standards, system types, and domain skills supported by:
* finalized experience;
* previous structured experience;
* or explicit JD requirements actually covered by established experience.

Do NOT add a skill solely because it appears in the JD.

A JD keyword may appear in the skills section only when established experience supports it.

Organize skills into meaningful categories.

Possible categories may include, when supported:
* Programming Languages
* Data Engineering
* Databases
* Cloud & Infrastructure
* Data Integration
* APIs & Interoperability
* Healthcare Technology
* Streaming & Distributed Systems
* Testing & Data Quality
* Automation
* DevOps
* Architecture
* Methodologies

Use only categories containing supported skills.

Avoid categories containing only one weak or loosely supported keyword when a more natural grouping is possible.

SKILL NORMALIZATION

Normalize obvious technology naming variations to standard industry terminology when appropriate.

For example:
* use `PySpark` consistently;
* use `Apache Spark` when referring to the platform generally;
* keep `HL7` and `FHIR` distinct when both are supported.

Do not modernize historical product names or introduce technologies that were not established.

SKILL DEDUPLICATION

Do not repeat the same skill across multiple categories unless there is a strong reason.

Prefer one canonical placement.

Avoid keyword stuffing.

Prioritize skills most relevant to the target JD.

COMPANY SUMMARIES

Generate one concise `company_summary` for each selected company.

Each company summary should:
* be approximately one sentence;
* explain the company/product context relevant to the candidate's work;
* help a recruiter understand the type of system or product associated with the experience;
* remain factual and concise.

Do not turn company summaries into additional accomplishment bullets.

Do not introduce unsupported:
* scale;
* customer counts;
* financial figures;
* market claims;
* product claims.

JD ALIGNMENT

Optimize the overall resume title, summary, skills, and presentation for the target JD while remaining evidence-grounded.

Prioritize:
1. critical and high-priority JD requirements;
2. must-have technologies;
3. major responsibilities;
4. system types;
5. domain terminology;
6. leadership or ownership expectations;
7. important business outcomes.

Do not repeatedly insert the same keyword merely for ATS purposes.

DOMAIN AND SPECIFICITY RULE

Match the specificity of the resume language to the established evidence.

Generic experience must not be transformed into unsupported domain-specific expertise.

For example:
* generic ETL experience does not automatically become healthcare data migration expertise;
* generic API work does not automatically become FHIR expertise;
* generic automation does not automatically become migration automation;
* generic leadership does not automatically become implementation leadership.

Use narrow domain terminology only when supported by established experience.

FINAL VALIDATION

Before returning the output, verify:
1. `resume_title` aligns with the target role.
2. Company 1 has exactly one role title.
3. Company 2 has exactly one role title.
4. Each company title matches its established role level and experience.
5. Company titles are not blindly copied from the target JD.
6. No company's seniority is artificially upgraded.
7. The professional summary contains only supported claims.
8. No unsupported years-of-experience statement was invented.
9. Every listed skill is supported by established experience.
10. JD-only skills without experience support are omitted.
11. Skills are grouped logically.
12. Duplicate skills are minimized.
13. Company summaries are factual and concise.
14. Company 1 retains exactly 6 Step 6 bullets.
15. Company 2 retains exactly 8 Step 6 bullets.
16. Step 6 bullet wording and ordering are unchanged.
17. No bullet metrics are modified.
18. No new experience is created.
19. No unsupported technology is introduced.
20. No timeline-incompatible terminology is introduced.
21. Domain-specific language matches the specificity of actual evidence.

Silently correct any inconsistency before returning the output.

OUTPUT

Return valid JSON only:

{
"resume_title": "",
"summary": "",
"skill_set": [
{
"category": "",
"skills": []
}
],
"experience": [
{
"company": "",
"product": "",
"timeline": "",
"title": "",
"company_summary": "",
"bullets": [
""
]
},
{
"company": "",
"product": "",
"timeline": "",
"title": "",
"company_summary": "",
"bullets": [
""
]
}
]
}

OUTPUT RULES

* JSON only.
* Generate one overall `resume_title`.
* Generate one `title` for Company 1.
* Generate one `title` for Company 2.
* Company 1 must retain exactly 6 bullets.
* Company 2 must retain exactly 8 bullets.
* Copy Step 6 bullets exactly; do not regenerate them.
* Generate only the overall resume title, company role titles, summary, skill set, and company summaries.
* Use only established evidence.
* Do not invent years of experience.
* Do not invent skills or technologies.
* Do not invent metrics or accomplishments.
* Do not add unsupported JD keywords.
* Do not artificially upgrade company role titles to match the target JD.
* Do not generate keyword/bracket formatting yet.
"""

DEFAULT_FINAL_RESUME_PROMPT = """You are continuing the same resume-tailoring workflow from the previous steps in this conversation.

Use all outputs already generated in this session. Do not ask me to provide previous outputs again.

TASK

Take the finalized resume content from Step 7 and produce the final structured resume with selective keyword marking.

This step is FORMAT-ONLY.

Do NOT rewrite, improve, regenerate, shorten, expand, reorder, or otherwise modify any resume content.

The Step 7 output is the final source of truth.

You must:
1. preserve the overall resume title exactly;
2. preserve the professional summary exactly;
3. preserve the skills exactly;
4. preserve both company names and products exactly;
5. preserve both company role titles exactly;
6. preserve both company summaries exactly;
7. preserve all Step 6 experience bullets exactly;
8. add selective keyword markers;
9. return the completed resume in the required XML structure.

CONTENT PRESERVATION RULE

Do not change any existing wording.

You may ONLY add square brackets around important words or phrases that already exist.

Do NOT:
* add words;
* remove words;
* replace words;
* correct wording;
* change grammar;
* change punctuation;
* change capitalization;
* change metrics;
* change technologies;
* change company titles;
* change resume title;
* change company summaries;
* change bullet order;
* change skill order;
* change company order.

All numeric values must remain exactly unchanged.

Company 1 must retain exactly 6 bullets.

Company 2 must retain exactly 8 bullets.

KEYWORD MARKING

Wrap important keywords or phrases in square brackets:

`[keyword]`

Mark recruiter-relevant and ATS-relevant terms such as:
* programming languages;
* technologies;
* tools;
* frameworks;
* platforms;
* databases;
* standards;
* protocols;
* methodologies;
* architectures;
* engineering capabilities;
* domain terminology;
* important system types;
* major target-role responsibilities.

Examples:

`Python`
-> `[Python]`

`Apache Spark`
-> `[Apache Spark]`

`data migration`
-> `[data migration]`

`HL7 and FHIR`
-> `[HL7] and [FHIR]`

Do not change the original wording while adding brackets.

SELECTIVITY RULE

Do not mark every possible keyword.

The purpose is to make the most important terms visually scannable.

For each experience bullet:
* mark approximately 2-4 important keywords or phrases;
* prefer the terms most relevant to the target JD;
* avoid marking ordinary verbs, filler words, metrics, or generic business language.

Do not exceed 4 marked keyword phrases in a bullet unless absolutely necessary.

For the professional summary:
* mark only the most important target-role keywords;
* generally use approximately 4-8 marked phrases across the entire summary;
* avoid excessive marking.

For company summaries:
* mark only 0-2 important phrases when useful;
* do not force keyword marking if the summary is primarily contextual.

SKILLS SECTION

The skills section is already composed of keywords.

Do not place square brackets around every individual skill.

Preserve the Step 7 skills exactly.

Make each skill category title bold using:

`<b>Category Name</b>`

Do not use Markdown asterisks.

Example:

`<category><name><b>Programming Languages</b></name><skills>Python, SQL</skills></category>`

Do not alter the skill names themselves.

KEYWORD PRIORITY

When deciding what to mark in the summary and bullets, prioritize:
1. critical JD requirements;
2. must-have technologies;
3. high-priority technical skills;
4. target-role responsibilities;
5. domain-specific terminology;
6. important system types;
7. leadership or architecture terminology when important to the target role.

Prefer exact JD terminology when that exact terminology already exists in the finalized resume.

Do not introduce missing JD keywords.

DOMAIN AND SPECIFICITY RULE

Do not make generic experience appear more domain-specific through keyword marking.

For example, if a bullet says:

`data pipelines`

do not change it to:

`[healthcare data pipelines]`

You may only mark:

`[data pipelines]`

because keyword marking cannot introduce new wording.

Likewise:

`integration`
must not become
`[FHIR integration]`

unless `FHIR integration` already exists in the source text.

PHRASE BOUNDARIES

Mark complete meaningful phrases when appropriate.

Prefer:

`[data migration]`

instead of:

`[data] migration`

Prefer:

`[Apache Spark]`

instead of:

`[Apache] [Spark]`

Prefer:

`[source-to-target mappings]`

instead of marking several individual words within the phrase.

Do not create nested brackets.

Do not overlap bracketed phrases.

METRICS

Do not mark metrics merely because they are impressive.

Keep numbers unchanged.

Example:

`reduced processing time by 47%`

Prefer marking the technical capability:

`reduced [ETL processing] time by 47%`

only if `ETL processing` already appears in the original text.

Do not bracket `47%` unless there is an exceptional reason.

COMPANY AND TITLE MARKING

Do not place keyword brackets around:
* company names;
* overall resume title;
* company role titles;
* timelines.

Preserve them exactly as finalized in Step 7.

FINAL VALIDATION

Before returning the output, verify:
1. The overall resume title is exactly unchanged from Step 7.
2. The professional summary wording is exactly unchanged except for added square brackets.
3. The skills and skill order are unchanged.
4. Company 1 role title is exactly unchanged.
5. Company 2 role title is exactly unchanged.
6. Company summaries are unchanged except for optional square brackets.
7. Company 1 contains exactly 6 bullets.
8. Company 2 contains exactly 8 bullets.
9. Every bullet is exactly unchanged except for added square brackets.
10. Every metric is exactly unchanged.
11. Every technology name is exactly unchanged.
12. No new keyword was introduced.
13. No word was removed.
14. No word was replaced.
15. Bullet ordering is unchanged.
16. Company ordering is unchanged.
17. Approximately 2-4 important phrases are marked per bullet.
18. Keyword marking is selective rather than excessive.
19. No nested or overlapping brackets exist.
20. Skill category titles use `<b>...</b>` rather than Markdown asterisks.
21. The returned XML is valid and complete.

Silently correct any formatting or preservation violation before returning the output.

OUTPUT FORMAT

Return ONLY the following XML structure.

Do not include Markdown fences, explanations, comments, or text outside the XML.

<resume>
  <resume_title></resume_title>

  <summary></summary>

  <skill_set>
    <category>
      <name><b></b></name>
      <skills></skills>
    </category>
    <category>
      <name><b></b></name>
      <skills></skills>
    </category>
  </skill_set>

  <experience>
    <company name="">
      <product></product>
      <timeline></timeline>
      <title></title>
      <company_summary></company_summary>
      <achievements>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
      </achievements>
    </company>

    <company name="">
      <product></product>
      <timeline></timeline>
      <title></title>
      <company_summary></company_summary>
      <achievements>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
        <bullet></bullet>
      </achievements>
    </company>
  </experience>
</resume>

OUTPUT RULES

* XML only.
* Do not regenerate resume content.
* Do not rewrite any Step 7 content.
* Only add square-bracket keyword markers.
* Preserve the finalized concise resume title exactly.
* Preserve both finalized company role titles exactly.
* Company 1 must contain exactly 6 bullets.
* Company 2 must contain exactly 8 bullets.
* Mark approximately 2-4 important keyword phrases per bullet.
* Do not over-mark.
* Do not use asterisks or Markdown bold.
* Use `<b>...</b>` only for skill category titles.
* Do not add or remove skills.
* Do not invent JD keywords.
* Do not alter metrics.
* Do not change ordering.
* Do not include explanations outside the XML.
"""

DEFAULT_VALIDATION_PROMPT = """You are continuing the same resume-tailoring workflow from the previous steps in this conversation.

Use all outputs already generated in this session. Do not ask me to provide previous outputs again.

TASK

Perform the final validation of the Step 8 resume before it is sent to the backend for PDF generation.

This step is VALIDATION-ONLY.

Do NOT rewrite, regenerate, improve, optimize, shorten, expand, reorder, or otherwise modify the resume.

The Step 8 XML is the final resume artifact.

Your job is to determine whether it is safe and ready for backend rendering.

Use all relevant outputs already established in this workflow, including:
* Step 1 Job Description analysis;
* Step 2 atomic requirements;
* Step 3 retrieved experience;
* Step 4 combined coverage and generation targets;
* Step 5 synthetic experience and final coverage;
* Step 6 finalized experience bullets and requirement mappings;
* Step 7 finalized titles, summary, skills, company summaries, and bullets;
* Step 8 final XML resume with selective keyword marking.

VALIDATION GOALS

Validate:
1. final XML structure;
2. resume-content preservation;
3. bullet counts;
4. metric preservation;
5. company and role consistency;
6. keyword-marker correctness;
7. skills consistency;
8. JD requirement coverage;
9. final job-match quality;
10. backend/PDF readiness.

RULE #1: DO NOT MODIFY THE RESUME

Do not produce a corrected resume.

Do not rewrite any content.

Do not propose replacement bullets inside the resume.

Do not alter:
* resume title;
* summary;
* skills;
* companies;
* products;
* timelines;
* role titles;
* company summaries;
* bullets;
* metrics;
* keyword markers.

If a problem exists, report it only.

RULE #2: XML VALIDATION

Validate the final Step 8 XML.

Confirm:
* exactly one `<resume>` root exists;
* all tags are properly opened and closed;
* XML nesting is valid;
* XML-reserved characters are correctly escaped;
* no raw textual `&` remains;
* no double-escaped XML entities exist;
* required `<b>...</b>` skill-category markup remains valid;
* no Markdown code fences exist;
* no explanatory text exists outside the XML artifact;
* company names in attributes are XML-safe.

Classify XML issues as:
* `blocking`
* `warning`
* `none`

Any XML issue that could prevent backend parsing must be `blocking`.

RULE #3: STEP 7 -> STEP 8 CONTENT PRESERVATION

Compare Step 8 against finalized Step 7 content.

Step 8 is allowed to differ ONLY through:
* added square-bracket keyword markers;
* required XML structure;
* `<b>...</b>` skill-category markup;
* required XML escaping.

Verify that Step 8 did NOT:
* add words;
* remove words;
* replace words;
* change grammar;
* change punctuation;
* change capitalization;
* alter technologies;
* alter metrics;
* alter titles;
* alter company summaries;
* alter skills;
* reorder skills;
* reorder bullets;
* reorder companies.

XML escaping must be treated as formatting, not content modification.

RULE #4: BULLET COUNT

Validate each company independently.

Company 1 must contain exactly 6 bullets.

Company 2 must contain exactly 8 bullets.

Do not rely on a combined total as the primary check.

If either company has the wrong bullet count, mark the resume as not backend-ready.

RULE #5: METRIC PRESERVATION

Compare numeric values in the final resume against their established Step 5 and Step 6 source facts.

Verify that no metric was:
* invented;
* changed;
* rounded;
* combined;
* extrapolated;
* removed in a way that changes the accomplishment;
* moved to another accomplishment incorrectly.

Metrics must remain exactly consistent with their established source experience.

Any changed or invented metric is a `blocking` issue.

RULE #6: COMPANY AND ROLE CONSISTENCY

Verify:
* Company 1 is the finalized fixed Company 1;
* Company 2 is the finalized selected Company 2;
* products and timelines match earlier finalized outputs;
* Company 1 role title matches its established role level;
* Company 2 role title matches its established role level;
* overall resume title remains the finalized concise title from Step 7.

Do not penalize the resume because the overall title differs from the individual company titles.

That distinction is intentional.

RULE #7: SKILLS VALIDATION

Verify that:
* Step 8 preserves the finalized Step 7 skills;
* no skill was added;
* no skill was removed;
* no skill was renamed;
* no skill was moved;
* no skill was deduplicated;
* category order is unchanged;
* skill order is unchanged;
* skill-category titles use valid `<name><b>...</b></name>` formatting.

Do not re-normalize the skills in this step.

RULE #8: KEYWORD-MARKER VALIDATION

Validate square-bracket keyword marking.

For each experience bullet:
* confirm there are 2-4 meaningful marked phrases;
* no bullet contains more than 4 marked phrases;
* marked phrases already existed in the original Step 7 text;
* no new wording was introduced through marking;
* brackets do not overlap;
* brackets are not nested;
* company names, role titles, product names, and timelines are not unnecessarily marked;
* metrics are not marked when a meaningful technical phrase can be marked instead.

For the professional summary:
* confirm no more than 8 marked phrases;
* marking remains selective and relevant.

For company summaries:
* allow 0-2 marked phrases.

Minor keyword-selection issues should normally be `warning`, not `blocking`, unless they alter content.

RULE #9: JD COVERAGE VALIDATION

Use the finalized atomic requirements and previous coverage outputs.

Evaluate whether the final resume adequately represents the important target-job requirements.

Focus on:
1. critical requirements;
2. high-priority requirements;
3. must-have technologies;
4. core responsibilities;
5. system types;
6. domain expertise;
7. leadership/seniority expectations;
8. business outcomes.

Use the established requirement evidence from Steps 4-6.

Do NOT infer new evidence from keyword overlap alone.

A requirement counts as strongly covered only when established experience directly supports it.

Generic cross-domain experience must not be treated as direct evidence for a narrow domain-specific requirement.

RULE #10: FINAL JOB-MATCH SCORE

Calculate a final internal job-match score from 0-100.

Use the established JD requirements and evidence, not superficial keyword frequency.

Recommended weighting:
* Critical requirements: 35%
* High-priority requirements: 25%
* Must-have technologies and system types: 15%
* Domain alignment: 10%
* Leadership/seniority alignment: 10%
* Preferred/nice-to-have requirements: 5%

For each requirement, consider:
* `strong` coverage = full or near-full credit;
* `partial` coverage = partial credit;
* `uncovered` = no credit.

Do not give extra credit simply because a keyword appears multiple times.

Do not inflate the score through broad requirement tagging.

The score should reflect actual evidence represented in the final resume.

RULE #11: CRITICAL COVERAGE CHECK

List any critical or high-priority requirement that remains:
* `partial`
* `uncovered`

Do not rewrite the resume to fix it.

Simply report the gap.

If an explicit must-have requirement remains genuinely uncovered, determine whether it should block backend readiness based on its importance.

RULE #12: BACKEND READINESS

Set:

`"backend_ready": true`

only when:
* XML is valid;
* bullet counts are correct;
* no resume content drift occurred;
* no metrics changed;
* required sections exist;
* company/product/title data is consistent;
* there are no blocking validation errors.

A lower-than-desired match score by itself does not necessarily make the XML technically invalid.

However, report the score and significant coverage gaps clearly.

ISSUE SEVERITY

Use:

`blocking`

for problems that should prevent PDF generation, such as:
* invalid XML;
* missing required sections;
* wrong bullet counts;
* changed or invented metrics;
* content corruption;
* missing company;
* significant Step 7 -> Step 8 content drift.

Use:

`warning`

for non-blocking quality concerns, such as:
* slightly weak keyword selection;
* minor over-marking;
* an important requirement remaining partial;
* a preferred skill remaining uncovered.

Use:

`info`

for observations that require no correction.

FINAL VALIDATION

Before returning the result, verify:
1. You did not rewrite the resume.
2. Step 8 XML was treated as immutable.
3. XML validity was checked.
4. Company 1 bullet count was checked independently.
5. Company 2 bullet count was checked independently.
6. Metrics were compared against established source facts.
7. Titles and timelines were checked.
8. Skills were checked for preservation.
9. Keyword-marker limits were checked.
10. Critical/high requirements were evaluated using actual evidence.
11. Final match score was not inflated through keyword frequency.
12. `backend_ready` reflects technical resume validity.
13. All blocking issues are explicitly listed.
14. No corrected resume content is returned.

OUTPUT

Return valid JSON only:

{
"validation_status": "pass",
"backend_ready": true,
"job_match_score": 0,
"xml_validation": {
"status": "pass",
"issues": []
},
"content_preservation": {
"status": "pass",
"issues": []
},
"bullet_count_validation": {
"company_1": {
"expected": 6,
"actual": 6,
"status": "pass"
},
"company_2": {
"expected": 8,
"actual": 8,
"status": "pass"
}
},
"metric_validation": {
"status": "pass",
"issues": []
},
"title_and_company_validation": {
"status": "pass",
"issues": []
},
"skills_validation": {
"status": "pass",
"issues": []
},
"keyword_marker_validation": {
"status": "pass",
"issues": []
},
"coverage_summary": {
"strong_requirement_ids": [],
"partial_requirement_ids": [],
"uncovered_requirement_ids": [],
"critical_or_high_gaps": []
},
"blocking_issues": [],
"warnings": [],
"final_recommendation": "Ready for backend rendering and PDF generation."
}

OUTPUT RULES

* JSON only.
* Do not return the resume XML again.
* Do not rewrite or correct resume content.
* Do not generate new resume bullets.
* Do not generate new synthetic experience.
* Validate against outputs already established in this session.
* Company 1 must have exactly 6 bullets.
* Company 2 must have exactly 8 bullets.
* Preserve strict metric traceability.
* Use evidence-based JD coverage.
* Do not inflate the match score through keyword repetition.
* Set `backend_ready` to false if any blocking issue exists.
* If `backend_ready` is true, the Step 8 XML may be sent unchanged to the backend for PDF generation.
"""

DEFAULT_SKILLS_PROMPT = """Extract the following from this job description:
1. Main Skills - the key technical and professional skills required, as a concise comma-separated list.
2. Job Mission - the core purpose of this role, in one sentence.
3. Industry - the industry this role belongs to, in a few words.

Respond in exactly this XML format and nothing else:
<extraction>
  <skills>comma-separated list</skills>
  <mission>one sentence</mission>
  <industry>industry name</industry>
</extraction>"""

# Used to turn selected challenges into resume bullets. Placeholders in braces
# are substituted before the prompt is sent; unknown ones are left untouched.
#
# {role_order} exists because both companies' bullets are generated in the
# SAME chat, one after the other -- without it, nothing in the prompt itself
# says which company this is relative to the other, and a model can blur the
# two together (echoing the wrong company's phrasing, treating the earlier
# role as the current one, etc.). See _ROLE_ORDER_LABELS in
# experience_service.py for the exact wording each call fills in.
DEFAULT_TAILORING_PROMPT = """Write exactly {count} resume bullet points for a role at {company} on {product} ({role_order}).

Rules:
- Output exactly {count} lines, one bullet per line, with no numbering or headings.
- Start each bullet with a strong past-tense verb.
- Keep every metric and fact exactly as given. Do not invent numbers, employers,
  dates, or technologies.
- Tailor the emphasis to the target job description below.

Target job description:
{job_description}

Source achievements:
{achievements}"""

# Substituted into the tailoring prompt. Surfaced in the Settings UI so the
# prompt can be edited without guessing what is available.
TAILORING_PLACEHOLDERS: tuple[str, ...] = (
    "count",
    "company",
    "product",
    "role_order",
    "job_description",
    "achievements",
)

# Runs last, in the same chat that just wrote the bullets, so the model already
# has them in context; {bullets} is included anyway so the prompt still works if
# the session drops and a fresh chat has to be opened.
DEFAULT_SUMMARY_PROMPT = """Write a {sentences}-sentence professional summary for the top of a resume targeting this role.

Rules:
- Output only the summary itself — no heading, no label, no bullet points, no quotes.
- Write in the implied first person: no "I", "my", or the candidate's name.
- Use only what the experience below supports. Do not invent employers, titles,
  metrics, technologies, or years of experience.
- Lead with the strongest match to the target role.

Target role: {job_title}

Target job description:
{job_description}

Experience just written for this resume ({companies}):
{bullets}"""

# Runs last, after the summary, in the same ChatGPT chat (step 5 in
# experience_service.py's extract_experience, see _draft_titles) -- ONE turn
# that asks for the resume-wide title and each company's own title together,
# rather than three separate asks sharing this one prompt. That used to be
# three calls, and each one, having no way to tell the model which single
# title THIS call wanted, tended to answer for everyone it already knew
# about regardless (observed: a single-title request came back as "Whole
# Profile Title: X / CompanyA: Y / CompanyB: Z"). Asking for all three
# explicitly removes the ambiguity instead of prompting around it.
#
# This step's reply is a DRAFT, not parsed against the labels it asks for --
# models kept drifting on the exact label wording (observed: the literal
# company name in place of "Job 1 Title") no matter how the request was
# worded, so it's folded as unstructured text into what step 8 sends
# ChatGPT instead, which is what actually finalizes the titles into clean,
# separated lines (see DEFAULT_REVISION_PROMPT's format request). This is
# pure style instruction either way, same split as the revision and
# keywords prompts below.
DEFAULT_TITLE_PROMPT = """Write the professional titles for this resume: one overall title for the top, and one for each company's own section below its name.

Rules:
- Keep each title under 60 characters.
- Use titles a recruiter would actually search for, not invented ones.
- Do not claim more seniority than the experience below supports.

Target role: {job_title}
Current title on the profile: {current_title}

Target job description:
{job_description}

Summary just written:
{summary}

Experience just written for this resume:
{bullets}"""

TITLE_PLACEHOLDERS: tuple[str, ...] = (
    "job_title",
    "current_title",
    "job_description",
    "summary",
    "bullets",
)

# Runs last in this chat, after the title -- before revision (steps 8-9,
# see _revise_with_chatgpt), still in the same chat. Where it lands on the
# rendered resume is up to the template's own "skills" block placement
# (default_layout() in backend/app/schemas/layout.py puts it right after
# Summary), not this prompt.
DEFAULT_SKILL_SET_PROMPT = """Write the skills section for this resume, as a list.

Rules:
- Output only a comma-separated list of skills. No heading, no numbering, no explanation.
- Use only skills the experience below actually supports. Do not invent skills
  that were not mentioned there.
- Prioritize skills that match the target job description, most relevant first.
- List 8-15 skills.

Target role: {job_title}

Target job description:
{job_description}

Experience just written for this resume:
{bullets}"""

SKILL_SET_PLACEHOLDERS: tuple[str, ...] = (
    "job_title",
    "job_description",
    "bullets",
)

# Runs right after that job's bullets are written, in the same chat, once per
# role (Job 1, then Job 2) -- so each one describes only that company/product,
# not the candidate as a whole the way the resume summary does.
DEFAULT_COMPANY_SUMMARY_PROMPT = """Write a {sentences}-sentence summary introducing this role, for the top of its section on a resume.

Rules:
- Output only the summary itself — no heading, no label, no bullet points, no quotes.
- Write in the implied first person: no "I", "my", or the candidate's name.
- Explain what {product} at {company} does and the scope of the role, so a
  recruiter understands the context before reading the bullets below it.
- Use only what the experience below supports. Do not invent employers, titles,
  metrics, technologies, or years of experience.
- Tailor the emphasis to the target role.

Target role: {job_title}

Target job description:
{job_description}

Bullets just written for this role:
{bullets}"""

COMPANY_SUMMARY_PLACEHOLDERS: tuple[str, ...] = (
    "sentences",
    "company",
    "product",
    "job_title",
    "job_description",
    "bullets",
)

# Step 7, still in the ChatGPT chat: everything above (titles, both
# companies' bullets and summaries, the overall summary, the skill set) was
# written across several turns -- this one asks ChatGPT to assemble it all
# into the complete resume content, using what it already has in context
# rather than that shape being built by Python string concatenation
# (_assemble_resume_content, the fallback for when this step is unavailable
# or its reply doesn't parse). No placeholders, and like the revision and
# keywords prompts below, nothing is appended in code -- sent to ChatGPT
# exactly as written on the Profile page (_build_whole_resume_message in
# experience_service.py). A reply that doesn't parse (e.g. _parse_final_reply
# finding no XML and no recognizable labels) just falls back to
# _assemble_resume_content instead of being rejected outright.
DEFAULT_WHOLE_RESUME_PROMPT = """Now put together the complete resume from everything written so far in this chat -- the bullets and summary for each company, and the overall summary.

Rules:
- Keep every fact, number, and technology exactly as already written. Do not invent or drop anything.
- Make the two companies' bullets consistent with each other in tone and level of detail.
- Do not shorten, combine, or drop any bullet."""

# Step 8, still in the same chat: revises the bullets, summary, and skill
# set this chat already wrote, and finalizes the resume's titles from step
# 5's draft into clean, separated lines. No placeholders — the resume
# content is included in the same message (see _build_revision_message in
# experience_service.py, which sends only that content plus this prompt
# exactly as written here, nothing appended), so this is pure style
# instruction, applied to "the resume I just gave you".
DEFAULT_REVISION_PROMPT = """Revise this resume.

- Keep a FAANG-style writing approach.
- Clearly explain the purpose and functionality of each project so recruiters and hiring managers can easily understand what it does.
- Include realistic, quantifiable achievements with accurate metrics.
- Make the bullets more realistic where needed.
- Naturally incorporate relevant technical skills into each bullet.
- Keep each bullet 2–3 lines long.
- Group the skill set into clear, conventional categories (e.g. Languages,
  Frameworks, Cloud & Infrastructure) rather than one long undifferentiated list.
- Write in natural, native English."""

# Step 9: one further message in that same chat, right after the revision
# above, so it still has the revised text in context (see
# _build_keyword_message in experience_service.py, which sends this prompt
# exactly as written here, nothing appended -- pure style instruction). The
# [bracket] marker is what the PDF renderer looks for to bold a word
# (RichText/parseBold in frontend/src/resume/format.ts).
DEFAULT_KEYWORDS_PROMPT = """Now mark the main keywords in the resume you just gave me.

- Wrap each important keyword or phrase in square brackets, like [REST API].
  Skills, technologies, tools, frameworks, methodologies, and other terms a
  recruiter or an ATS would search for all count.
- Do not change any wording, and do not add or remove anything — only add the
  bracket markers around words or phrases that are already there.
- Do not use asterisks, double asterisks, or any other markdown.
- Mark at most 2-4 keywords per bullet. Marking too much makes nothing stand out."""

# The prompt used to produce a profile's database.json. Stored only — the
# application never sends it. It is kept here so the wording that produced a
# corpus is recorded beside the corpus, rather than living in someone's notes
# app, and so the next profile can start from the same instructions.
#
# Written to stand alone, with the schema inline and no placeholders, because
# it is copied into an AI tool by hand. A {token} nothing substitutes would be
# pasted verbatim and confuse the model.
DEFAULT_CORPUS_PROMPT = """Convert my experience into a career database, as JSON.

Rules:
- Output only the JSON array. No markdown fence, no commentary before or after.
- Use only what my experience states. Do not invent employers, products, dates,
  metrics, or technologies. If something is not stated, leave it out.
- Give every challenge a unique id: lowercase, company_product_project_challengeN.
- industry is the product's industry (e.g. Fintech, Healthcare, Education) --
  the same value at the product level and on every challenge under it.
- challenge, action, achievement and business_impact are one sentence each.
- seniority_indicator describes scope: who was led, who it was presented to.
- Split each role into two projects where my experience describes two distinct
  pieces of work, and give each project two challenges where there is enough
  detail for two. Where there is not, write fewer — one real challenge beats two
  with an invented half.

Schema:
[
  {
    "company": "Acme",
    "product": "Acme Payments",
    "industry": "Fintech",
    "timeline": "2019 - 2022",
    "summary": "One sentence on what the product does and my part in it.",
    "projects": [
      {
        "name": "Settlement pipeline",
        "description": "One sentence on the project.",
        "challenges": [
          {
            "id": "acme_payments_settlement_challenge1",
            "industry": "Fintech",
            "challenge": "The problem, in one sentence.",
            "action": "What I did about it, in one sentence.",
            "achievement": "The measurable result, in one sentence.",
            "business_impact": "Why it mattered to the business.",
            "seniority_indicator": "Who I led and who I presented to."
          }
        ]
      }
    ]
  }
]

My experience:
"""

SUMMARY_PLACEHOLDERS: tuple[str, ...] = (
    "sentences",
    "job_title",
    "job_description",
    "companies",
    "bullets",
)

DEFAULTS: dict[str, Any] = {
    # New pipeline architecture, step 1 -- see DEFAULT_REQUIREMENTS_PROMPT.
    "requirementsPrompt": DEFAULT_REQUIREMENTS_PROMPT,
    # Step 2 -- see DEFAULT_MATCHING_REQUIREMENTS_PROMPT.
    "matchingRequirementsPrompt": DEFAULT_MATCHING_REQUIREMENTS_PROMPT,
    # Step 4 (step 3 is pure Python, no prompt) -- see DEFAULT_SELECTION_PROMPT.
    "selectionPrompt": DEFAULT_SELECTION_PROMPT,
    # Step 5 -- see DEFAULT_SYNTHETIC_GENERATION_PROMPT.
    "syntheticGenerationPrompt": DEFAULT_SYNTHETIC_GENERATION_PROMPT,
    # Step 6 -- see DEFAULT_BULLETS_PROMPT.
    "bulletsPrompt": DEFAULT_BULLETS_PROMPT,
    # Step 7 -- see DEFAULT_RESUME_CONTENT_PROMPT.
    "resumeContentPrompt": DEFAULT_RESUME_CONTENT_PROMPT,
    # Step 8 -- see DEFAULT_FINAL_RESUME_PROMPT.
    "finalResumePrompt": DEFAULT_FINAL_RESUME_PROMPT,
    # Step 9 -- see DEFAULT_VALIDATION_PROMPT.
    "validationPrompt": DEFAULT_VALIDATION_PROMPT,
    "skillsPrompt": DEFAULT_SKILLS_PROMPT,
    "tailoringPrompt": DEFAULT_TAILORING_PROMPT,
    # Step 4: a resume summary written from the bullets the pipeline just made.
    "summaryPrompt": DEFAULT_SUMMARY_PROMPT,
    # Step 5: the headline titles (resume-wide + each company's own),
    # written together in one turn once the summary exists.
    "titlePrompt": DEFAULT_TITLE_PROMPT,
    # Steps 3a/3b: one summary per role (Job 1, Job 2), introducing that
    # company/product above its bullets.
    "companySummaryPrompt": DEFAULT_COMPANY_SUMMARY_PROMPT,
    # Step 6: the resume's skill set, written in this chat.
    "skillSetPrompt": DEFAULT_SKILL_SET_PROMPT,
    # Step 7: ChatGPT assembles everything above into the complete resume,
    # still in this same chat, before steps 8-9 revise it.
    "wholeResumePrompt": DEFAULT_WHOLE_RESUME_PROMPT,
    # Step 8: revises the bullets and summary, still in this same chat.
    "revisionPrompt": DEFAULT_REVISION_PROMPT,
    # Step 9: a further message in that same chat, marking keywords.
    "keywordsPrompt": DEFAULT_KEYWORDS_PROMPT,
    # Not part of extraction: builds a profile's database.json on demand.
    "corpusPrompt": DEFAULT_CORPUS_PROMPT,
    "outputFolder": "",
    # Which signed-in provider Phase 5 uses to generate content.
    "generationModel": "deepseek",
    # Company used as Job 1 (the earlier role) in experience extraction.
    # Scoped to a profile, not the user: each profile has its own corpus, so a
    # company valid for one is meaningless for another.
    "firstCompany": "",
    # The first company's timeline, years only. Job 1 runs start->end and Job 2
    # runs end->present, so two numbers fix both roles' dates on every tailored
    # resume. Profile-scoped for the same reason firstCompany is.
    "firstCompanyStartYear": "",
    "firstCompanyEndYear": "",
    # How much a challenge's industry-similarity score counts toward its
    # final ranking score during Job 1/Job 2 selection -- see
    # INDUSTRY_SIMILARITY_WEIGHT in experience_service.py, which falls back
    # to this same default when nothing is stored. 0-1; profile-scoped like
    # firstCompany, since what counts as "this profile's industry fit" is
    # meaningless outside the corpus it's tuning search over.
    "industryWeight": "0.35",
    # Profile whose details and template are used for tailored resume PDFs, and
    # whose name becomes "<Profile>_resume.pdf". Empty = use the first profile.
    "resumeProfile": "",
}

ALLOWED_MODELS = ("deepseek", "chatgpt")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Old enough to cover any working career, and a future year is always a typo.
EARLIEST_YEAR = 1950


def _validate_year(key: str, value: Any) -> str:
    """A four-digit year, or empty. Resumes carry years, never months."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.isdigit() or len(text) != 4:
        raise ValueError(f"{key} must be a four-digit year, e.g. 2019.")
    year = int(text)
    this_year = datetime.now(timezone.utc).year
    if year < EARLIEST_YEAR or year > this_year:
        raise ValueError(f"{key} must be between {EARLIEST_YEAR} and {this_year}.")
    return text


# Settings that belong to one resume identity rather than the whole account.
PROFILE_SCOPED: frozenset[str] = frozenset(
    {"firstCompany", "firstCompanyStartYear", "firstCompanyEndYear", "industryWeight"}
)

PROMPT_KEYS: dict[str, str] = {
    "requirementsPrompt": "requirements",
    "matchingRequirementsPrompt": "matchreqs",
    "selectionPrompt": "selection",
    "syntheticGenerationPrompt": "synthetic",
    "bulletsPrompt": "bullets",
    "resumeContentPrompt": "resumecontent",
    "finalResumePrompt": "finalresume",
    "validationPrompt": "validation",
    "skillsPrompt": "skills",
    "tailoringPrompt": "tailoring",
    "summaryPrompt": "summary",
    "titlePrompt": "title",
    "companySummaryPrompt": "companysummary",
    "skillSetPrompt": "skillset",
    "wholeResumePrompt": "wholeresume",
    "revisionPrompt": "revision",
    "keywordsPrompt": "keywords",
    "corpusPrompt": "corpus",
}


def _active_profile():
    """The profile whose settings apply. None before any profile exists."""
    from app.services import job_store

    try:
        return job_store.active_profile_id()
    except Exception:  # noqa: BLE001 - no profile yet is a normal first-run state
        return None


def get_settings() -> dict[str, Any]:
    """Stored settings merged over defaults, so a new key never returns None."""
    from app.bootstrap import current_user_id

    user_id = current_user_id()
    stored: dict[str, Any] = {}

    profile_id = _active_profile()

    with get_db() as conn:
        for row in conn.execute(
            select(settings.c.key, settings.c.value).where(
                settings.c.scope == "user", settings.c.user_id == user_id
            )
        ):
            stored[row.key] = row.value

        # Profile-scoped values win, and are the only source for their keys.
        if profile_id is not None:
            for row in conn.execute(
                select(settings.c.key, settings.c.value).where(
                    settings.c.scope == "profile", settings.c.profile_id == profile_id
                )
            ):
                stored[row.key] = row.value

        by_kind = {v: k for k, v in PROMPT_KEYS.items()}
        for row in conn.execute(
            select(prompts.c.kind, prompts.c.body).where(
                prompts.c.scope == "user", prompts.c.user_id == user_id
            )
        ):
            if row.kind in by_kind:
                stored[by_kind[row.kind]] = row.body

        # Profile-scoped prompts win over the account-wide ones just loaded,
        # same "overwrite what's already there" pattern as the settings block
        # above -- each profile gets its own prompts, falling back to
        # whatever was customized account-wide, then to DEFAULTS.
        if profile_id is not None:
            for row in conn.execute(
                select(prompts.c.kind, prompts.c.body).where(
                    prompts.c.scope == "profile", prompts.c.profile_id == profile_id
                )
            ):
                if row.kind in by_kind:
                    stored[by_kind[row.kind]] = row.body

    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def validate_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Reject unknown keys and invalid values before anything is written."""
    cleaned: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise ValueError(f"Unknown setting: {key!r}")

        if key == "generationModel":
            if value not in ALLOWED_MODELS:
                raise ValueError(
                    f"generationModel must be one of {', '.join(ALLOWED_MODELS)}"
                )
        elif key == "outputFolder":
            if value:
                path = Path(str(value)).expanduser()
                if not path.is_absolute():
                    raise ValueError("Output folder must be an absolute path.")
                if not path.exists():
                    raise ValueError(f"Folder does not exist: {path}")
                if not path.is_dir():
                    raise ValueError(f"Not a folder: {path}")
                value = str(path)
        elif key == "firstCompany":
            if value:
                # Reject a company that isn't in this profile's corpus now,
                # rather than letting extraction fail later with a confusing
                # error. Validated against the active profile, because that is
                # the corpus the extraction will actually read.
                from app.services import experience_db_store, job_store

                try:
                    db = experience_db_store.load_database(job_store.active_profile_id())
                except Exception:  # noqa: BLE001 - no corpus yet, or a broken one
                    db = None
                if db is not None and db.find_company(str(value)) is None:
                    raise ValueError(
                        f"{value!r} is not a company in this profile's database.json."
                    )
                value = str(value).strip()
        elif key in ("firstCompanyStartYear", "firstCompanyEndYear"):
            value = _validate_year(key, value)
        elif key == "industryWeight":
            try:
                weight = float(value)
            except (TypeError, ValueError):
                raise ValueError("industryWeight must be a number.")
            if not 0.0 <= weight <= 1.0:
                raise ValueError("industryWeight must be between 0 and 1.")
            value = str(weight)
        elif key == "resumeProfile":
            if value:
                # A deleted profile would otherwise fail at generation time with
                # a 404 that says nothing about where the stale id came from.
                from app.services import profile_service

                value = str(value).strip()
                if all(p.id != value for p in profile_service.list_profiles()):
                    raise ValueError("That profile no longer exists.")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be text.")

        cleaned[key] = value

    # Cross-field, so it can only run once both values are known. A patch may
    # carry one year, so the other comes from what is already stored — saving
    # an end year alone must still be checked against the stored start.
    if "firstCompanyStartYear" in cleaned or "firstCompanyEndYear" in cleaned:
        stored = get_settings()
        start = cleaned.get("firstCompanyStartYear", stored.get("firstCompanyStartYear", ""))
        end = cleaned.get("firstCompanyEndYear", stored.get("firstCompanyEndYear", ""))
        if start and end and int(end) < int(start):
            raise ValueError(
                f"The first company's end year ({end}) is before its start year ({start})."
            )

    return cleaned


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    cleaned = validate_settings(patch)
    from app.bootstrap import current_user_id
    from app.ids import uuid7

    user_id = current_user_id()
    profile_id = _active_profile()

    with get_db() as conn:
        for key, value in cleaned.items():
            if kind := PROMPT_KEYS.get(key):
                # Each profile gets its own prompts once one exists -- the
                # partial unique index covers (profile_id, kind) where the
                # scope is 'profile'. Unlike PROFILE_SCOPED settings below,
                # this does not raise when there's no active profile yet: a
                # prompt still has a meaningful account-wide fallback value
                # (get_settings() reads it back via the scope='user' tier),
                # so degrading to that instead of a hard failure is correct
                # here -- in practice this branch is barely reachable anyway,
                # since the only prompt-editing UI only renders once a
                # profile is selected.
                if profile_id is not None:
                    statement = pg_insert(prompts).values(
                        id=uuid7(),
                        scope="profile",
                        profile_id=profile_id,
                        kind=kind,
                        body=str(value),
                    )
                    conn.execute(
                        statement.on_conflict_do_update(
                            index_elements=[prompts.c.profile_id, prompts.c.kind],
                            index_where=text("scope = 'profile'"),
                            set_={"body": statement.excluded.body, "updated_at": func.now()},
                        )
                    )
                else:
                    # The partial unique index covers (user_id, kind) where
                    # the scope is 'user', which is what makes this upsert
                    # land on one row instead of accumulating revisions.
                    statement = pg_insert(prompts).values(
                        id=uuid7(),
                        scope="user",
                        user_id=user_id,
                        kind=kind,
                        body=str(value),
                    )
                    conn.execute(
                        statement.on_conflict_do_update(
                            index_elements=[prompts.c.user_id, prompts.c.kind],
                            index_where=text("scope = 'user'"),
                            set_={"body": statement.excluded.body, "updated_at": func.now()},
                        )
                    )
            elif key in PROFILE_SCOPED:
                if profile_id is None:
                    raise ValueError(
                        f"{key} belongs to a profile, and none exists yet."
                    )
                statement = pg_insert(settings).values(
                    id=uuid7(),
                    scope="profile",
                    profile_id=profile_id,
                    key=key,
                    value=value,
                )
                conn.execute(
                    statement.on_conflict_do_update(
                        index_elements=[settings.c.profile_id, settings.c.key],
                        index_where=text("scope = 'profile'"),
                        set_={"value": statement.excluded.value, "updated_at": func.now()},
                    )
                )
            else:
                statement = pg_insert(settings).values(
                    id=uuid7(),
                    scope="user",
                    user_id=user_id,
                    key=key,
                    value=value,
                )
                conn.execute(
                    statement.on_conflict_do_update(
                        index_elements=[settings.c.user_id, settings.c.key],
                        index_where=text("scope = 'user'"),
                        set_={"value": statement.excluded.value, "updated_at": func.now()},
                    )
                )
    return get_settings()


def render_template(text: str, values: dict[str, Any]) -> str:
    """Substitute {placeholders} without str.format's brace fragility.

    A user prompt may legitimately contain braces (JSON examples, code), which
    str.format would treat as fields and raise on. Only the keys actually
    supplied are replaced; anything else is left exactly as written.
    """
    rendered = text or ""
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def check_folder(path_text: str) -> dict[str, Any]:
    """Report whether a folder is usable for saving generated documents."""
    raw = (path_text or "").strip()
    if not raw:
        return {"valid": False, "detail": "Enter a folder path."}
    path = Path(raw).expanduser()
    if not path.is_absolute():
        return {"valid": False, "detail": "Please use an absolute path."}
    if not path.exists():
        return {"valid": False, "detail": "That folder does not exist."}
    if not path.is_dir():
        return {"valid": False, "detail": "That path is a file, not a folder."}

    # Writability is what actually matters, and it can't be inferred reliably
    # from permissions on Windows — so test it directly.
    try:
        # A unique temporary file avoids colliding with or deleting a file the
        # user may already have created with a fixed probe name.
        with tempfile.NamedTemporaryFile(prefix=".jobtailor-write-test-", dir=path):
            pass
    except OSError as exc:
        return {"valid": False, "detail": f"Folder is not writable: {exc.strerror or exc}"}

    return {"valid": True, "detail": f"Ready to save into {path}", "resolved": str(path)}


def _show_folder_dialog(initial_directory: Path) -> str:
    """Open the host operating system's native directory chooser."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        root.update_idletasks()
        return str(
            filedialog.askdirectory(
                parent=root,
                title="Select JobTailor output folder",
                initialdir=str(initial_directory),
                mustexist=True,
            )
            or ""
        )
    finally:
        root.destroy()


def select_folder(initial_path: str | None = None) -> dict[str, Any]:
    """Open a folder chooser and validate the selected directory immediately."""
    initial = Path(initial_path).expanduser() if initial_path else Path.home()
    if not initial.exists() or not initial.is_dir():
        initial = Path.home()

    selected = _show_folder_dialog(initial)
    if not selected:
        return {
            "cancelled": True,
            "valid": False,
            "detail": "Folder selection cancelled.",
        }

    result = check_folder(selected)
    return {"cancelled": False, **result}
