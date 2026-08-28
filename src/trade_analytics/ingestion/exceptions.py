"""Domain exceptions raised by the UN Comtrade ingestion package."""


class ComtradeError(Exception):
    """Base exception for ingestion failures."""


class ComtradeRequestError(ComtradeError):
    """The HTTP request failed or exhausted its retries."""


class ComtradeAuthenticationError(ComtradeRequestError):
    """The remote service rejected authentication or authorization."""


class ComtradeResponseError(ComtradeError):
    """The remote response was malformed or reported an API error."""


class ResponseTruncatedError(ComtradeResponseError):
    """The preview response reached its maximum record count."""


class EmptyDataError(ComtradeResponseError):
    """No records remained after applying the requested query contract."""


class DataContractError(ComtradeResponseError):
    """One or more response records violated the ingestion contract."""
