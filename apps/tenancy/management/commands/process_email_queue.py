from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.crm.email_delivery import resolve_tenant_mail_route
from apps.tenancy.models import EmailQueue


class Command(BaseCommand):
    help = "Process pending tenant emails in EmailQueue."

    def handle(self, *args, **options):
        pending = EmailQueue.objects.filter(status=EmailQueue.STATUS_PENDING).order_by("created_at")[:200]
        if not pending:
            self.stdout.write(self.style.SUCCESS("No pending emails."))
            return

        sent_count = 0
        failed_count = 0

        for item in pending:
            from_email, connection = resolve_tenant_mail_route(item.tenant)
            email = EmailMultiAlternatives(
                subject=item.subject,
                body=item.text_body,
                from_email=from_email,
                to=[item.to_email],
                connection=connection,
            )
            if item.html_body:
                email.attach_alternative(item.html_body, "text/html")

            try:
                email.send(fail_silently=False)
                item.status = EmailQueue.STATUS_SENT
                item.sent_at = timezone.now()
                item.attempts += 1
                item.last_error = ""
                item.save(update_fields=["status", "sent_at", "attempts", "last_error"])
                sent_count += 1
            except Exception as first_exc:
                fallback_email = EmailMultiAlternatives(
                    subject=item.subject,
                    body=item.text_body,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local"),
                    to=[item.to_email],
                )
                if item.html_body:
                    fallback_email.attach_alternative(item.html_body, "text/html")

                try:
                    fallback_email.send(fail_silently=False)
                    item.status = EmailQueue.STATUS_SENT
                    item.sent_at = timezone.now()
                    item.attempts += 1
                    item.last_error = ""
                    item.save(update_fields=["status", "sent_at", "attempts", "last_error"])
                    sent_count += 1
                except Exception as exc:
                    item.status = EmailQueue.STATUS_FAILED
                    item.attempts += 1
                    item.last_error = f"primary={first_exc}; fallback={exc}"
                    item.save(update_fields=["status", "attempts", "last_error"])
                    failed_count += 1

        self.stdout.write(self.style.SUCCESS(f"Processed email queue. sent={sent_count}, failed={failed_count}"))
