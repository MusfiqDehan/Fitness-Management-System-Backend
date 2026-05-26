import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('reminder', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='recipient',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='targeted_notifications',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('tenant_registered', 'Tenant Registered'),
                    ('tenant_subscribed', 'Tenant Subscribed'),
                    ('member_onboarded', 'Member Onboarded'),
                    ('trainer_onboarded', 'Trainer Onboarded'),
                    ('welcome_member', 'Welcome Member'),
                    ('welcome_trainer', 'Welcome Trainer'),
                    ('class_booking_confirmed', 'Class Booking Confirmed'),
                    ('new_booking_received', 'New Booking Received'),
                    ('booking_cancelled', 'Booking Cancelled'),
                ],
            ),
        ),
    ]
