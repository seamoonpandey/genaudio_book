"""Blob storage — Tigris/S3 when BUCKET_NAME set, local disk under DATA_DIR/files otherwise."""
import os
from pathlib import Path

_client = None


def _bucket():
    return os.environ.get("BUCKET_NAME") or os.environ.get("S3_BUCKET")


def _s3():
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))
    return _client


def _local(key) -> Path:
    return Path(os.environ.get("DATA_DIR", ".")) / "files" / key


def put(key: str, data: bytes):
    if _bucket():
        _s3().put_object(Bucket=_bucket(), Key=key, Body=data)
    else:
        p = _local(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def get(key: str) -> bytes:
    if _bucket():
        return _s3().get_object(Bucket=_bucket(), Key=key)["Body"].read()
    return _local(key).read_bytes()


def url(key: str) -> str:
    """Playable URL: presigned (1h) on S3, /files static mount locally."""
    if _bucket():
        return _s3().generate_presigned_url(
            "get_object", Params={"Bucket": _bucket(), "Key": key}, ExpiresIn=3600
        )
    return f"/files/{key}"


def delete_prefix(prefix: str):
    if _bucket():
        pages = _s3().get_paginator("list_objects_v2").paginate(Bucket=_bucket(), Prefix=prefix)
        for page in pages:
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                _s3().delete_objects(Bucket=_bucket(), Delete={"Objects": objs})
    else:
        root = _local(prefix)
        if root.is_dir():
            import shutil
            shutil.rmtree(root)
