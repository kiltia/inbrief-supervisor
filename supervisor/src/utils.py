import string

import torch
from nltk.tokenize import sent_tokenize, word_tokenize

LOGGING_FORMAT = "[%(levelname)s] [%(asctime)s] %(message)s"
DATE_FORMAT = "%m/%d/%y %H:%M:%S"
DEFAULT_END_DATE = "01/01/01 00:00:00"
