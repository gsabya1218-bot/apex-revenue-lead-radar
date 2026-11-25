import unittest

from app.linkedin_signals import (
    build_queries, classify, company_guess, evidence_level, infer_timeline, parse_date
)


class LinkedInSignalTests(unittest.TestCase):
    def test_search_volume_is_ninety_queries(self):
        self.assertEqual(len(build_queries()), 90)

    def test_linkedin_job_is_classified_as_hiring_signal(self):
        kind = classify(
            "https://www.linkedin.com/jobs/view/123456/",
            "Director Consumer Insights - Acme Foods",
            "Requires syndicated market data and consumer panels",
        )
        self.assertEqual(kind, "data_insights_hiring_signal")

    def test_project_brief_requires_request_language(self):
        kind = classify(
            "https://www.linkedin.com/posts/example/",
            "Seeking a consultant for consumer insights project",
            "Need market sizing and CAGR analysis",
        )
        self.assertEqual(kind, "consulting_project_brief")

    def test_hiring_is_not_promoted_to_p1(self):
        status, _score = evidence_level(
            "data_insights_hiring_signal",
            "Head of Insights role requiring consumer data and syndicated data",
            "within 4 weeks",
        )
        self.assertEqual(status, "P3_HIRING_SIGNAL_ONLY")

    def test_job_company_extraction(self):
        company = company_guess(
            "Director, Consumer Insights - Acme Foods - United States",
            "New role",
            "https://www.linkedin.com/jobs/view/123456/",
        )
        self.assertEqual(company, "Acme Foods")

    def test_timeline_extraction(self):
        self.assertIsNotNone(infer_timeline("Please submit by December 3"))

    def test_relative_date_parsing(self):
        self.assertIsNotNone(parse_date("2 days ago"))
        self.assertIsNone(parse_date("date unavailable"))


if __name__ == "__main__":
    unittest.main()
