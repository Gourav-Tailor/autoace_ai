# audio_analytics/management/commands/create_device_token.py
"""
Usage:
    python manage.py create_device_token <username> "<device name>"

Example:
    python manage.py create_device_token gourav "Living Room ESP32"
    python manage.py create_device_token gourav "iPhone App"

Prints the API token the device/app should send as:
    Authorization: Token <key>
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

from audio_analytics.models import Device


class Command(BaseCommand):
    help = "Create a Device + API token for a user, for ESP32/Raspberry Pi/mobile clients."

    def add_arguments(self, parser):
        parser.add_argument("username", type=str)
        parser.add_argument("device_name", type=str)

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"No such user: {options['username']}")

        token, _ = Token.objects.get_or_create(user=user)

        device, created = Device.objects.get_or_create(
            user=user,
            name=options["device_name"],
            defaults={"api_token": token},
        )
        if not created and device.api_token_id != token.id:
            device.api_token = token
            device.save(update_fields=["api_token"])

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} device '{device.name}' for user '{user.username}'.\n"
            f"API Token: {token.key}\n\n"
            f"Have the device send this header on every request:\n"
            f"  Authorization: Token {token.key}"
        ))