import boto3
from botocore.config import Config
from django.conf import settings
from storages.backends.s3 import S3Storage


class MinIOStorage(S3Storage):
    """
    MinIO storage backend.

    Internal Docker endpoint:
        http://minio:9000

    Public endpoint for browser playback:
        http://34.148.248.202:9000

    Uploads/storage operations continue using the internal endpoint.
    Presigned playback URLs are generated against the public endpoint.
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
            config=Config(
                signature_version="s3v4",
                s3={
                    "addressing_style": settings.AWS_S3_ADDRESSING_STYLE,
                },
            ),
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
            HttpMethod=http_method or "GET",
        )
