"""Download a small, curated public-paper reading set (no login or scraping).

python3 -m research.literature
PDFs and provenance stay in ignored data/literature/. No SIG credentials used.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


PAPERS = [
    ("bafumi-2010-balancing", "Balancing, Generic Polls and Midterm Congressional Elections",
     "10.1017/S0022381610000113", "Author manuscript dated December 4, 2008; journal publication 2010",
     "https://www.columbia.edu/~rse14/bafumi_erikson_wlezien_balancing.pdf"),
    ("knight-2015-midterm-gap", "An Econometric Evaluation of Competing Explanations for the Midterm Gap",
     "10.3386/w20311", "NBER working paper 20311; revised November 2015",
     "https://www.nber.org/system/files/working_papers/w20311/w20311.pdf"),
    ("shirani-mehr-poll-errors", "Disentangling Bias and Variance in Election Polls",
     "10.1080/01621459.2018.1448823", "Published article hosted by author; 2018",
     "https://sites.stat.columbia.edu/gelman/research/published/polling-errors.pdf"),
    ("knight-2017-midterm-gap", "An Econometric Evaluation of Competing Explanations for the Midterm Gap",
     "10.1561/100.00015008", "Published version, Quarterly Journal of Political Science 12:205-239; 2017",
     "https://bpb-us-w2.wpmucdn.com/sites.brown.edu/dist/d/75/files/2019/05/An-Econometric-Evaluation-of-Competing-Explanations-for-the-Midterm-Gap.pdf"),
    ("tierney-2025-poll-errors", "Bias and excess variance in election polling: a not-so-hidden Markov model",
     "10.1093/jrsssa/qnae066", "Published article; online July 2024, issue April 2025",
     "https://par.nsf.gov/servlets/purl/10593294"),
    ("erikson-2008-markets-polls", "Are Political Markets Really Superior to Polls as Election Predictors?",
     "10.1093/poq/nfn010", "Published article hosted at Columbia",
     "https://statmodeling.stat.columbia.edu/wp-content/uploads/2024/08/Erikson-and-Wlezien-POQ-2008.pdf"),
    ("rothschild-2009-markets-polls", "Forecasting Elections: Comparing Prediction Markets, Polls, and Their Biases",
     "10.1093/poq/nfp082", "Published article hosted by author",
     "https://researchdmr.com/files/ForecastingElectionMarketsPolls.pdf"),
]

DATASETS = [
    ("chen-senate-replication.zip", "10.7910/DVN/GNHESM", "Dataverse V1, CC0; code/data capsule only, not 28.8 GB results archive",
     "https://dataverse.harvard.edu/api/access/datafile/5130867"),
    ("tierney-polls-2020.csv", "10.1093/jrsssa/qnae066", "Author replication data; main branch snapshot; preserve hash",
     "https://raw.githubusercontent.com/g-tierney/polling_errors_replication/main/data/polls_auxiliary_dataset_2020Update.csv"),
]


def fetch_asset(url):
    request = Request(url, headers={"User-Agent": "ElectionLiteratureResearch/1.0"})
    with urlopen(request, timeout=35) as response:
        body = response.read(25_000_001)
        if len(body) > 25_000_000:
            raise ValueError("Response exceeds 25 MB limit")
        return body, response.url


def fetch_pdf(url):
    body, final_url = fetch_asset(url)
    if not body.startswith(b"%PDF-"):
        raise ValueError("Response is not a PDF; use browser for access issues")
    return body, final_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/literature")
    parser.add_argument("--datasets-only", action="store_true", help="Collect two public replication assets instead of papers; do not execute code")
    args = parser.parse_args()
    # Separate runs preserve original files and access-failure records.
    output = args.output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    items = ([(Path(name).stem, name, doi, version, url) for name, doi, version, url in DATASETS]
             if args.datasets_only else PAPERS)
    for slug, title, doi, version, url in items:
        record = dict(id=slug, title=title, doi=doi, version=version, url=url,
                      retrieved_at=datetime.now(timezone.utc).isoformat())
        try:
            body, final_url = (fetch_asset if args.datasets_only else fetch_pdf)(url)
            if args.datasets_only and title.endswith(".zip") and not body.startswith(b"PK"):
                raise ValueError("Response is not a ZIP")
            if args.datasets_only and title.endswith(".csv") and b"<html" in body[:1024].lower():
                raise ValueError("HTML returned instead of data")
            target = output / (title if args.datasets_only else slug + ".pdf")
            target.write_bytes(body)
            record.update(status="downloaded", file=target.name, bytes=len(body),
                          sha256=hashlib.sha256(body).hexdigest(), final_url=final_url)
        except Exception as exc:
            record.update(status="access_failed", error=f"{type(exc).__name__}: {exc}")
        records.append(record)
        (output / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
        print(f"{slug}: {record['status']}", flush=True)
    print(f"Provenance: {output / 'manifest.json'}")


if __name__ == "__main__":
    main()
