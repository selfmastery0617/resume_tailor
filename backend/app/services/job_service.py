from app.schemas.job import JobListing

# Placeholder in-memory data. Replace with real scraping/API integration later.
_MOCK_JOBS = [
    JobListing(id="1", title="Software Engineer", company="Acme Corp", location="Remote", url="https://example.com/jobs/1"),
    JobListing(id="2", title="Data Analyst", company="Globex", location="New York, NY", url="https://example.com/jobs/2"),
    JobListing(id="3", title="Product Manager", company="Initech", location="Austin, TX", url="https://example.com/jobs/3"),
]


def get_jobs() -> list[JobListing]:
    return _MOCK_JOBS
