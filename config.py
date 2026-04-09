import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Credentials ---
BLUESKY_HANDLE = os.getenv("BLUESKY_HANDLE")
BLUESKY_APP_PASSWORD = os.getenv("BLUESKY_APP_PASSWORD")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY")
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")  # e.g. digest@yourdomain.com
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

# --- Pipeline settings ---
LOOKBACK_DAYS = 7
SECOND_DEGREE_CAP = 1000
GRAPH_REFRESH_DAYS = 30
# --- Journals: name -> list of ISSNs ---
JOURNALS = {
    "Journal of Marketing Research": ["0022-2437", "1547-7193"],
    "Journal of Marketing": ["0022-2429", "1547-7185"],
    "Journal of Consumer Research": ["0093-5301", "1537-5277"],
    "Marketing Science": ["0732-2399", "1526-548X"],
    "Journal of the Academy of Marketing Science": ["0092-0703", "1552-7824"],
    "Journal of Consumer Psychology": ["1057-7408", "1532-7663"],
    "Journal of Retailing": ["0022-4359"],
    "International Journal of Research in Marketing": ["0167-8116"],
    "Journal of Interactive Marketing": ["1094-9968", "1520-6653"],
    "Journal of Public Policy & Marketing": ["0743-9156", "1547-7207"],
    "Journal of Advertising": ["0091-3367", "1557-7805"],
    "Journal of Advertising Research": ["0021-8499", "1740-1909"],
    "Journal of Business Research": ["0148-2963"],
    "Journal of Service Research": ["1094-6705", "1552-7379"],
    "Management Science": ["0025-1909", "1526-5501"],
    "Harvard Business Review": ["0017-8012"],
    "MIT Sloan Management Review": ["1532-9194"],
    "Psychological Science": ["0956-7976", "1467-9280"],
    "Journal of Personality and Social Psychology": ["0022-3514", "1939-1315"],
    "Journal of Experimental Psychology: General": ["0096-3445", "1939-2222"],
    "Computers in Human Behavior": ["0747-5632"],
    "Information Systems Research": ["1047-7047", "1526-5536"],
    "MIS Quarterly": ["0276-7783", "2162-9730"],
    "Technological Forecasting and Social Change": ["0040-1625"],
    "Research Policy": ["0048-7333"],
    "Journal of Product Innovation Management": ["0737-6782", "1540-5885"],
}
