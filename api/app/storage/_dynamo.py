from decimal import Decimal

import boto3


def _table(name: str):
    return boto3.resource("dynamodb").Table(name)


def _to_ddb(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _to_ddb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_ddb(item) for item in value]
    return value


def _from_ddb(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _from_ddb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_ddb(item) for item in value]
    return value
