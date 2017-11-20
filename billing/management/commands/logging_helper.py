import logging
import sys


def setup_logging(verbose):
    # Log WARN and above to stderr
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.WARN)
    logging.root.addHandler(err)

    # Log everything below WARN to stdout
    out = logging.StreamHandler(sys.stdout)
    out.setLevel(logging.NOTSET)
    out.addFilter(lambda r: r.levelno < logging.WARN)
    logging.root.addHandler(out)

    if verbose:
        logging.root.setLevel(logging.DEBUG)
    else:
        logging.root.setLevel(logging.INFO)
