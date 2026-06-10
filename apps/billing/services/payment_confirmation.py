"""Dispatch payment confirmation emails and in-app notifications."""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django_tenants.utils import schema_context

from apps.crm.email_delivery import resolve_tenant_mail_route
from apps.dashboard.models import GymProfile, NotificationPreferences
from apps.identity.models import User
from apps.reminder.models import Notification
from apps.reminder.utils import create_notification

logger = logging.getLogger(__name__)

ACTIVE_CHANNELS = frozenset({"email", "in_app"})


def _filter_channels(channels: list[str] | None) -> list[str]:
    if not channels:
        return []
    return [c for c in channels if c in ACTIVE_CHANNELS]


def _member_user(member):
    if not member:
        return None
    if member.email:
        user = User.objects.filter(email__iexact=member.email, role="student").first()
        if user:
            return user
    if member.phone_number:
        return User.objects.filter(phone=member.phone_number, role="student").first()
    return None


def _tenant_billing_email(tenant) -> str:
    if tenant is None:
        return ""
    return (getattr(tenant, "billing_email", "") or getattr(tenant, "owner_email", "") or "").strip()


def _gym_name() -> str:
    profile = GymProfile.objects.first()
    return (profile.gym_name if profile and profile.gym_name else "Your Gym") or "Your Gym"


def _should_send_admin_email() -> bool:
    prefs = NotificationPreferences.objects.first()
    return prefs is None or prefs.payment_received


def dispatch_member_payment(payment, channels: list[str] | None, *, actor=None, tenant=None) -> None:
    """Send member payment confirmation email and/or in-app notifications."""
    active = _filter_channels(channels)
    if not active:
        return

    member = payment.member
    if member is None:
        return

    tenant_name = _gym_name()
    actor_name = getattr(actor, "full_name", None) or getattr(actor, "email", "") or "Staff"
    invoice_no = payment.invoice_no or f"INV-{payment.id:06d}"
    amount = str(payment.amount)

    if "email" in active and member.email:
        try:
            from apps.billing.views import _render_payment_invoice_pdf

            pdf_bytes = _render_payment_invoice_pdf(payment, tenant_name, actor_name)
            context = {
                "member_name": member.full_name,
                "amount": amount,
                "invoice_no": invoice_no,
                "gym_name": tenant_name,
            }
            html_body = render_to_string("billing/emails/payment_confirmation.html", context)
            text_body = (
                f"Hi {member.full_name},\n\n"
                f"Your payment of {amount} has been received. Invoice: {invoice_no}.\n\n"
                f"Thank you,\n{tenant_name}"
            )
            from_email, connection = resolve_tenant_mail_route(tenant)
            recipients = [member.email]
            billing_email = ""
            if tenant:
                billing_email = _tenant_billing_email(tenant)
            if billing_email and _should_send_admin_email():
                recipients.append(billing_email)

            email = EmailMultiAlternatives(
                subject=f"Payment confirmation — {invoice_no}",
                body=text_body,
                from_email=from_email,
                to=recipients,
                connection=connection,
            )
            email.attach_alternative(html_body, "text/html")
            email.attach(f"invoice-{invoice_no}.pdf", pdf_bytes, "application/pdf")
            email.send(fail_silently=True)
        except Exception:
            logger.exception("Failed to send member payment confirmation email payment_id=%s", payment.id)

    if "in_app" in active:
        member_user = _member_user(member)
        if member_user:
            try:
                create_notification(
                    notification_type=Notification.PAYMENT_CONFIRMED,
                    title="Payment confirmed",
                    message=f"Your payment of {amount} ({invoice_no}) was recorded.",
                    actor_name=actor_name,
                    target_type="payment",
                    target_id=str(payment.id),
                    recipient=member_user,
                )
            except Exception:
                logger.exception("Failed personal payment notification payment_id=%s", payment.id)

        try:
            create_notification(
                notification_type=Notification.PAYMENT_RECEIVED,
                title="Payment received",
                message=f"{member.full_name} paid {amount} ({invoice_no}).",
                actor_name=actor_name,
                target_type="payment",
                target_id=str(payment.id),
            )
        except Exception:
            logger.exception("Failed broadcast payment notification payment_id=%s", payment.id)


def dispatch_subscription_invoice(invoice, channels: list[str] | None, *, actor=None) -> None:
    """Notify tenant admins about a platform subscription payment."""
    active = _filter_channels(channels)
    if not active:
        return

    tenant = invoice.tenant
    if tenant is None:
        return

    tenant_schema = tenant.schema_name
    amount = f"{invoice.currency} {invoice.amount}"
    package_name = invoice.package_name or invoice.package_slug
    actor_name = getattr(actor, "email", "") or "Platform Admin"

    with schema_context(tenant_schema):
        if "email" in active:
            billing_email = _tenant_billing_email(tenant)
            if billing_email:
                try:
                    from apps.billing.views import _render_subscription_invoice_pdf

                    pdf_bytes = _render_subscription_invoice_pdf(invoice, actor_name)
                    context = {
                        "tenant_name": tenant.name,
                        "package_name": package_name,
                        "amount": amount,
                        "tran_id": invoice.tran_id,
                    }
                    html_body = render_to_string("billing/emails/subscription_confirmation.html", context)
                    text_body = (
                        f"Subscription payment confirmed for {tenant.name}.\n"
                        f"Package: {package_name}\nAmount: {amount}\nRef: {invoice.tran_id}"
                    )
                    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@gym.local")
                    email = EmailMultiAlternatives(
                        subject=f"Subscription payment confirmed — {invoice.tran_id}",
                        body=text_body,
                        from_email=from_email,
                        to=[billing_email],
                    )
                    email.attach_alternative(html_body, "text/html")
                    email.attach(f"subscription-invoice-{invoice.tran_id}.pdf", pdf_bytes, "application/pdf")
                    email.send(fail_silently=True)
                except Exception:
                    logger.exception("Failed subscription confirmation email invoice_id=%s", invoice.id)

        if "in_app" in active:
            try:
                create_notification(
                    notification_type=Notification.SUBSCRIPTION_PAYMENT_CONFIRMED,
                    title="Subscription payment confirmed",
                    message=f"{package_name} — {amount} ({invoice.tran_id})",
                    actor_name=actor_name,
                    target_type="subscription_invoice",
                    target_id=str(invoice.id),
                )
            except Exception:
                logger.exception("Failed subscription in-app notification invoice_id=%s", invoice.id)
