"""Output format shared by the football predictor and its downstream readers."""

SCHEMA = "football-jc-integrated-forecast-v1"
LEGACY_VERSIONS = frozenset(("football-jc-poisson-asian-assimilation-v4",
                             "football-jc-integrated-v5"))


def compatible(forecast):
    schema = forecast.get("forecast_schema")
    if schema is None:
        return forecast.get("model_version") in LEGACY_VERSIONS
    return schema == SCHEMA and isinstance(forecast.get("model_version"), str) and bool(forecast["model_version"])
