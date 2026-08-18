from urllib.parse import urlparse

import boto3
from django.conf import settings
from storages.backends.s3 import S3Storage


class MinIOStorage(S3Storage):
    """
    Use the internal Docker MinIO endpoint for uploads/downloads,
    but generate presigned URLs against the public MinIO endpoint.
    """

    def url(self, name, parameters=None, expire=None, http_method=None):
        if expire is None:
            expire = settings.AWS_QUERYSTRING_EXPIRE

        client = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_PUBLIC_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
            config=self.connection.meta.config,
        )

        params = {
            "Bucket": self.bucket_name,
            "Key": name,
        }

        if parameters:
            params.update(parameters)

        return client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expire,
            HttpMethod=http_method,
        )