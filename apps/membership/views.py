from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
from .models import Member, Attendance


class CheckAccessAPIView(APIView):

    def post(self, request):

        # Device Security
        api_key = request.headers.get("X-API-KEY")
        if api_key != settings.GYM_DEVICE_API_KEY:
            return Response({"access": False}, status=403)

        card_id = request.data.get("card_id")
        fingerprint_id = request.data.get("fingerprint_id")
        device_id = request.data.get("device_id")

        member = None

        if card_id:
            member = Member.objects.filter(card_id=card_id).first()

        if fingerprint_id:
            member = Member.objects.filter(fingerprint_id=fingerprint_id).first()

        if not member:
            return Response({
                "access": False,
                "message": "Member not found"
            })

        if not member.is_valid:
            return Response({
                "access": False,
                "message": "Membership expired or inactive"
            })

        # Check if member already inside
        open_attendance = Attendance.objects.filter(
            member=member,
            check_out_time__isnull=True
        ).first()

        #  If inside → Check OUT
        if open_attendance:
            open_attendance.check_out_time = timezone.now()
            open_attendance.save()

            return Response({
                "access": True,
                "action": "checked_out",
                "member_name": member.full_name
            })

        #  If NOT inside → Check IN

        # Prevent duplicate tap within 20 seconds
        last_entry = Attendance.objects.filter(
            member=member
        ).order_by('-check_in_time').first()

        if last_entry:
            time_diff = timezone.now() - last_entry.check_in_time
            if time_diff < timedelta(seconds=20):
                return Response({
                    "access": False,
                    "message": "Duplicate scan detected"
                })

        Attendance.objects.create(
            member=member,
            entry_method="card" if card_id else "fingerprint",
            device_id=device_id
        )

        return Response({
            "access": True,
            "action": "checked_in",
            "member_name": member.full_name,
            "remaining_days": member.remaining_days
        })


class MembersInsideAPIView(APIView):

    def get(self, request):

        inside_members = Attendance.objects.filter(
            check_out_time__isnull=True
        ).select_related('member')

        data = []

        for record in inside_members:
            data.append({
                "member_name": record.member.full_name,
                "phone": record.member.phone_number,
                "check_in_time": record.check_in_time
            })

        return Response({
            "total_inside": inside_members.count(),
            "members": data
        })