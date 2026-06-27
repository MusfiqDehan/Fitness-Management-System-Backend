"""Class detail, enrollment roster, and member-facing class APIs."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access.permissions import HasFeatureMethodPermission
from utils.list_mixins import SearchFilterSortPaginationMixin
from utils.pagination import StandardPagination

from .models import ClassEnrollment, GymClass, GymSchedule
from .serializers import (
    ClassEnrollmentMemberSerializer,
    GymClassDetailSerializer,
    GymScheduleSerializer,
    MemberClassEnrollmentSerializer,
)
from .services.class_attendance import ClassAttendanceService, InvalidPunctualityValue
from .services.class_enrollment import (
    CapacityExceeded,
    ClassEnrollmentService,
    ClassEnrollmentServiceError,
)


class _ClassDetailMixin:
    feature_key = 'classes'
    permission_classes = [HasFeatureMethodPermission]

    def _get_gym_class(self, pk: int) -> GymClass | None:
        return (
            GymClass.objects.filter(pk=pk, is_deleted=False)
            .select_related('trainer_profile__user', 'trainer_class')
            .first()
        )

    def _enrollment_service(self, request) -> ClassEnrollmentService:
        return ClassEnrollmentService(user=request.user)


class GymClassDetailAPIView(_ClassDetailMixin, APIView):
    """GET /membership/gym-classes/{id}/detail/"""

    def get(self, request, pk):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        service = self._enrollment_service(request)
        stats = service.get_detail_stats(gym_class)
        data = GymClassDetailSerializer(gym_class).data
        data.update(stats)
        return Response(data)


class GymClassSchedulesAPIView(_ClassDetailMixin, SearchFilterSortPaginationMixin, APIView):
    """GET /membership/gym-classes/{id}/schedules/"""

    pagination_class = StandardPagination

    def get(self, request, pk):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        qs = self._enrollment_service(request).list_class_schedules(gym_class)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = GymScheduleSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class GymClassMembersAPIView(_ClassDetailMixin, SearchFilterSortPaginationMixin, APIView):
    """GET/POST/DELETE /membership/gym-classes/{id}/members/"""

    feature_keys = ['classes', 'classes.bookings']
    method_permission_map = {'GET': 'view', 'POST': 'edit', 'DELETE': 'edit'}
    pagination_class = StandardPagination

    def get(self, request, pk):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        search = request.query_params.get('search')
        ordering = request.query_params.get('ordering', '-enrolled_at')
        qs = self._enrollment_service(request).list_enrolled_members(
            gym_class, search=search, ordering=ordering
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = ClassEnrollmentMemberSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, pk):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        member_ids = request.data.get('member_ids', [])
        if not member_ids or not isinstance(member_ids, list):
            return Response({'member_ids': ['Required list of member IDs.']}, status=status.HTTP_400_BAD_REQUEST)
        sync_future = request.data.get('sync_future_sessions', True)
        notify_channels = request.data.get('notify_channels') or []
        if notify_channels and not isinstance(notify_channels, list):
            return Response(
                {'notify_channels': ['Must be a list of notification channels.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant = getattr(request, 'tenant', None)
        try:
            enrollments = self._enrollment_service(request).enroll_members(
                gym_class,
                member_ids,
                sync_future_sessions=bool(sync_future),
                notify_channels=notify_channels,
                tenant=tenant,
            )
        except CapacityExceeded as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except ClassEnrollmentServiceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            ClassEnrollmentMemberSerializer(enrollments, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, pk):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        member_ids = request.data.get('member_ids', [])
        if not member_ids or not isinstance(member_ids, list):
            return Response({'member_ids': ['Required list of member IDs.']}, status=status.HTTP_400_BAD_REQUEST)
        removed = self._enrollment_service(request).remove_members(gym_class, member_ids)
        return Response({'removed': removed})


class GymClassTrainerAPIView(_ClassDetailMixin, APIView):
    """PATCH /membership/gym-classes/{id}/trainer/"""

    def patch(self, request, pk):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        trainer_profile_id = request.data.get('trainer_profile_id')
        if not trainer_profile_id:
            return Response(
                {'trainer_profile_id': ['Required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            updated = self._enrollment_service(request).assign_trainer(gym_class, int(trainer_profile_id))
        except ClassEnrollmentServiceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        from .serializers import GymClassSerializer
        return Response(GymClassSerializer(updated).data)


class GymClassAttendanceAPIView(_ClassDetailMixin, SearchFilterSortPaginationMixin, APIView):
    """GET /membership/gym-classes/{id}/attendance/"""

    pagination_class = StandardPagination

    def get(self, request, pk):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        search = request.query_params.get('search')
        rows = ClassAttendanceService.list_class_attendance(gym_class, search=search)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


class GymClassAttendanceItemAPIView(_ClassDetailMixin, APIView):
    """PATCH /membership/gym-classes/{id}/attendance/{booking_id}/"""

    feature_keys = ['classes', 'classes.bookings']
    method_permission_map = {'PATCH': 'edit'}

    def patch(self, request, pk, booking_id):
        gym_class = self._get_gym_class(pk)
        if gym_class is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        booking = ClassAttendanceService.get_class_booking(gym_class, booking_id)
        if booking is None:
            return Response({'detail': 'Booking not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'punctuality' not in request.data:
            return Response(
                {'punctuality': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        punctuality = request.data.get('punctuality')
        if punctuality is not None and punctuality != '' and not isinstance(punctuality, str):
            return Response(
                {'punctuality': ['Must be a string or null.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if punctuality == '':
            punctuality = None

        try:
            row = ClassAttendanceService.set_punctuality_override(
                booking,
                punctuality,
                user=request.user,
            )
        except InvalidPunctualityValue as exc:
            return Response({'punctuality': [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)

        schedule = booking.schedule
        from apps.membership.services.class_attendance import resolve_session_date

        return Response({
            'booking_id': booking.id,
            'member_id': booking.member_id,
            'member_name': booking.member.full_name,
            'session_date': resolve_session_date(schedule),
            'start_time': schedule.start_time,
            'end_time': schedule.end_time,
            'status': booking.status,
            'source': booking.source,
            **row,
        })


class GymScheduleBookingsAPIView(APIView):
    """POST/DELETE /membership/gym-schedules/{id}/bookings/"""

    feature_key = 'classes.bookings'
    permission_classes = [HasFeatureMethodPermission]

    def post(self, request, pk):
        gym_schedule = GymSchedule.objects.filter(pk=pk, is_deleted=False).select_related(
            'trainer_schedule', 'gym_class'
        ).first()
        if gym_schedule is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        member_ids = request.data.get('member_ids', [])
        if not member_ids:
            return Response({'member_ids': ['Required.']}, status=status.HTTP_400_BAD_REQUEST)
        service = ClassEnrollmentService(user=request.user)
        try:
            bookings = service.assign_members_to_schedule(gym_schedule, member_ids)
        except ClassEnrollmentServiceError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        from apps.trainer.serializers import ScheduleBookingSerializer
        return Response(
            ScheduleBookingSerializer(bookings, many=True, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, pk):
        gym_schedule = GymSchedule.objects.filter(pk=pk, is_deleted=False).select_related(
            'trainer_schedule'
        ).first()
        if gym_schedule is None or gym_schedule.trainer_schedule_id is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        booking_ids = request.data.get('booking_ids', [])
        if not booking_ids:
            return Response({'booking_ids': ['Required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.trainer.models import ScheduleBooking

        cancelled = 0
        for booking in ScheduleBooking.objects.filter(
            pk__in=booking_ids,
            schedule_id=gym_schedule.trainer_schedule_id,
            is_deleted=False,
        ).select_related('schedule'):
            schedule = booking.schedule
            booking.status = 'cancelled'
            booking.save(update_fields=['status', 'updated_at'])
            schedule.current_participants = max(0, schedule.current_participants - 1)
            schedule.is_full = False
            schedule.save(update_fields=['current_participants', 'is_full'])
            cancelled += 1
        return Response({'cancelled': cancelled})


class MyClassEnrollmentsAPIView(APIView):
    """GET /membership/my-enrollments/ — member's class-level enrollments."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'detail': 'Member profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        enrollments = ClassEnrollment.objects.filter(
            member=member,
            status='active',
            is_deleted=False,
        ).select_related('gym_class__trainer_profile__user').order_by('-enrolled_at')
        return Response(MemberClassEnrollmentSerializer(enrollments, many=True).data)


class MyClassAttendanceAPIView(APIView):
    """GET /membership/my-class-attendance/ — member class session attendance."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'detail': 'Member profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        day = request.query_params.get('day')
        month = request.query_params.get('month')
        year = request.query_params.get('year')
        month_int = int(month) if month else None
        year_int = int(year) if year else None
        rows = ClassAttendanceService.list_member_class_attendance(
            member,
            day=day,
            month=month_int,
            year=year_int,
        )
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 10))
        start = (page - 1) * page_size
        end = start + page_size
        total = len(rows)
        return Response({
            'count': total,
            'total_pages': max(1, (total + page_size - 1) // page_size),
            'page': page,
            'page_size': page_size,
            'results': rows[start:end],
        })
