"""S3 兼容对象存储后端：生产指向腾讯云 COS，验收指向本地 MinIO。

boto3 走 S3 协议；endpoint_url 可配（COS 指向 COS endpoint，MinIO 指向
本地 minio:9000，真 AWS S3 留空默认）。写：pyarrow 写 BytesIO 后 put_object；
读：get_object 到 BytesIO 用 pyarrow 读。
"""
from __future__ import annotations

import io
from typing import Any

from app.cold_storage.base import ColdStorage


class S3ColdStorage(ColdStorage):
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        region: str | None,
    ) -> None:
        if not bucket or not access_key or not secret_key:
            raise ValueError(
                "s3 后端缺配置：COLD_S3_BUCKET / COLD_S3_ACCESS_KEY / "
                "COLD_S3_SECRET_KEY 均必填"
            )
        import boto3

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def write_parquet(
        self,
        key: str,
        rows: list[dict[str, Any]],
        *,
        sort_by: list[str],
    ) -> str:
        import pyarrow as pa
        import pyarrow.parquet as pq

        try:
            table = pa.Table.from_pylist(rows)
            if sort_by:
                # pyarrow sort_by 需 [(列名, 方向), ...] 形式，统一升序
                table = table.sort_by([(c, "ascending") for c in sort_by])
            buf = io.BytesIO()
            pq.write_table(table, buf, compression="snappy")
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=buf.getvalue()
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"s3 后端写 Parquet 失败 bucket={self._bucket} key={key!r}: {e}"
            ) from e
        return f"s3://{self._bucket}/{key}"

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise

    def read_parquet(self, key: str) -> list[dict[str, Any]]:
        import pyarrow.parquet as pq

        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
            return pq.read_table(io.BytesIO(obj["Body"].read())).to_pylist()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"s3 后端读 Parquet 失败 bucket={self._bucket} key={key!r}: {e}"
            ) from e

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            for item in resp.get("Contents", []):
                if item["Key"].endswith(".parquet"):
                    keys.append(item["Key"])
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return keys
