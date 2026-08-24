/** Demonstration data.
 *
 *  Used unconditionally on the Templates and Builder pages (TM-FR-009's
 *  labeling requirement still applies -- the preview always shows the
 *  "Sample data" badge, see ResumePreview's isSample prop): judging a
 *  template/style against a real profile is misleading when that profile is
 *  sparse, since a thin section can make a layout look broken when it isn't.
 *  This exists to exercise every section a template can have, so every
 *  field here should stay populated -- an empty one is a gap in the fixture,
 *  not a realistic case to represent.
 */

import type { ResumeData } from "./types";

export const SAMPLE_RESUME: ResumeData = {
  profile: {
    fullName: "Alex Chen",
    professionalTitle: "Senior Backend Engineer",
    email: "alex.chen@example.com",
    phone: "(555) 010-4477",
    street: "128 Harbor Street",
    city: "Austin",
    state: "TX",
    postal: "78701",
    birthday: "1990-05-14",
    linkedin: "linkedin.com/in/alexchen",
    website: "alexchen.dev",
    summary:
      "Backend engineer with 8 years building **distributed services** at scale. " +
      "Focused on reliability, developer experience, and pragmatic API design.",
  },
  experience: [
    {
      id: "exp-1",
      company: "Northwind Systems",
      title: "Senior Backend Engineer",
      location: "Remote",
      startDate: "Mar 2021",
      endDate: "",
      current: true,
      companySummary: "Platform engineering for a high-volume logistics network.",
      description:
        "Led migration of a monolith to **event-driven services**, cutting p99 latency by 42%.\n" +
        "Designed the public REST API now serving 30M requests per day.\n" +
        "Mentored five engineers and introduced a lightweight RFC process.",
    },
    {
      id: "exp-2",
      company: "Bright Harbor Analytics",
      title: "Backend Engineer",
      location: "Austin, TX",
      startDate: "Jun 2018",
      endDate: "Feb 2021",
      current: false,
      companySummary: "Analytics products for operational and product teams.",
      description:
        "Built the ingestion pipeline processing 4TB of daily telemetry.\n" +
        "Reduced infrastructure spend 28% by right-sizing the warehouse workload.",
    },
  ],
  education: [
    {
      id: "edu-1",
      university: "University of Texas at Austin",
      degree: "B.S. Computer Science",
      startYear: "2013",
      endYear: "2017",
      location: "Austin, TX",
    },
  ],
  skills: [
    { id: "sk-1", name: "Python", category: "Languages" },
    { id: "sk-2", name: "TypeScript", category: "Languages" },
    { id: "sk-3", name: "Go", category: "Languages" },
    { id: "sk-4", name: "PostgreSQL", category: "Data" },
    { id: "sk-5", name: "Kafka", category: "Data" },
    { id: "sk-6", name: "AWS", category: "Infrastructure" },
    { id: "sk-7", name: "Kubernetes", category: "Infrastructure" },
    { id: "sk-8", name: "Mentoring", category: "" },
  ],
};
