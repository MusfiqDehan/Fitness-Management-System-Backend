# Generated migration for membership models with BaseModel fields
# NOTE: Member.created_at already exists from 0001_initial.py
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('membership', '0002_alter_member_start_date'),
    ]

    operations = [
        # Add BaseModel fields to MemberPackage
        migrations.AddField(
            model_name='memberpackage',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_memberpackage_created_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_memberpackage_deleted_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='display_order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='updated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_memberpackage_updated_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='add_ons',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='memberpackage',
            name='features',
            field=models.JSONField(blank=True, default=list),
        ),

        # Add BaseModel fields + new fields to Member
        # NOTE: created_at for Member already exists in 0001_initial.py
        migrations.AddField(
            model_name='member',
            name='address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='member',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_member_created_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='member',
            name='date_of_birth',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='member',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='member',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_member_deleted_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='member',
            name='email',
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.AddField(
            model_name='member',
            name='emergency_contact_name',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='member',
            name='emergency_contact_phone',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='member',
            name='gender',
            field=models.CharField(
                blank=True,
                choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='member',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='member',
            name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='member',
            name='notes',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='member',
            name='payment_method',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AddField(
            model_name='member',
            name='payment_status',
            field=models.CharField(blank=True, default='unpaid', max_length=20),
        ),
        migrations.AddField(
            model_name='member',
            name='photo',
            field=models.ImageField(blank=True, null=True, upload_to='members/photos/'),
        ),
        migrations.AddField(
            model_name='member',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='member',
            name='updated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_member_updated_records',
                to='identity.User',
            ),
        ),

        # Add BaseModel fields + new fields to Payment
        migrations.AddField(
            model_name='payment',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_payment_created_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_payment_deleted_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='payment',
            name='is_paid',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='payment',
            name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='payment',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='updated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_payment_updated_records',
                to='identity.User',
            ),
        ),

        # Add BaseModel fields + new fields to Attendance
        migrations.AddField(
            model_name='attendance',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='attendance',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_attendance_created_records',
                to='identity.User',
            ),
        ),
        migrations.AddField(
            model_name='attendance',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='attendance',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_attendance_deleted_records',
                to='identity.User',
            ),
        ),
        # NOTE: device_id already exists in 0001_initial.py - do not add again
        migrations.AddField(
            model_name='attendance',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='attendance',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='attendance',
            name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='attendance',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='attendance',
            name='updated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='membership_attendance_updated_records',
                to='identity.User',
            ),
        ),
    ]