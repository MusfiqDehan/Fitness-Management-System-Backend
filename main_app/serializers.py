from rest_framework import serializers
import json
from .models import (
    Banner,
    GymClub, 
    Facility,
    GymClass, 
    Category, 
    ClassSchedule,
    Blog, 
    BlogCategory,
    Contact,
    FitHiveSupport,
    ClassBooking,
    Package, 
    PackageFeature, 
    PackageAddOn
)
from django.utils import timezone
from accounts.models import InstructorProfile

# banner serializer
class BannerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Banner
        fields = '__all__'

# --- Gym Club Serializer ---

class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = ['id', 'name']

class GymClubSerializer(serializers.ModelSerializer):
    facilities = FacilitySerializer(many=True, required=False)

    class Meta:
        model = GymClub
        fields = '__all__'

    def to_internal_value(self, data):
        facilities = data.get('facilities')

        if isinstance(facilities, str):
            data._mutable = True
            data['facilities'] = json.loads(facilities)

        return super().to_internal_value(data)

    def create(self, validated_data):
        gym = GymClub.objects.create(**validated_data)

        facilities_data = self.initial_data.get('facilities')

        if facilities_data:
            if isinstance(facilities_data, str):
                facilities_data = json.loads(facilities_data)

            for facility in facilities_data:
                name = facility.get('name')
                if name:
                    obj, _ = Facility.objects.get_or_create(name=name)
                    gym.facilities.add(obj)

        return gym

    def update(self, instance, validated_data):
        # Update normal fields first
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        # 🔥 Get facilities from raw request data
        facilities_data = self.initial_data.get('facilities')

        if facilities_data:
            if isinstance(facilities_data, str):
                facilities_data = json.loads(facilities_data)

            instance.facilities.clear()

            for facility in facilities_data:
                name = facility.get('name')
                if name:
                    obj, _ = Facility.objects.get_or_create(name=name)
                    instance.facilities.add(obj)

        return instance
# class GymClubSerializer(serializers.ModelSerializer):
#     facilities = serializers.PrimaryKeyRelatedField(
#         queryset=Facility.objects.all(),
#         many=True,
#         required=False
#     )


#     class Meta:
#         model = GymClub
#         fields = '__all__'

    # def create(self, validated_data):
    #     facilities_data = validated_data.pop('facilities', [])
    #     if isinstance(facilities_data, str):
    #         facilities_data = json.loads(facilities_data)  # parse JSON string

    #     gym = GymClub.objects.create(**validated_data)

    #     for facility in facilities_data:
    #         obj, _ = Facility.objects.get_or_create(**facility)
    #         gym.facilities.add(obj)

    #     return gym

    # def update(self, instance, validated_data):
    #     facilities_data = validated_data.pop('facilities', None)
    #     if isinstance(facilities_data, str):
    #         facilities_data = json.loads(facilities_data)

    #     # Update other fields
    #     for attr, value in validated_data.items():
    #         setattr(instance, attr, value)
    #     instance.save()

    #     # Update facilities
    #     if facilities_data is not None:
    #         instance.facilities.clear()
    #         for facility in facilities_data:
    #             obj, _ = Facility.objects.get_or_create(**facility)
    #             instance.facilities.add(obj)

    #     return instance

# class
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class ClassScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassSchedule
        fields = ["id", "day", "time"]


class GymClassSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source="category",
        write_only=True
    )

    class_schedule = ClassScheduleSerializer(read_only=True, many=True)
    class_schedule_ids = serializers.PrimaryKeyRelatedField(
        queryset=ClassSchedule.objects.all(),
        source="class_schedule",
        write_only=True,
        many=True
    )
    instructor_name = serializers.SerializerMethodField()

    class Meta:
        model = GymClass
        fields = [
            "id",
            "title",
            "image",
            "description",
            "category",
            "category_id",
            "class_duration",
            "people",
            "level",
            "class_schedule",
            "class_schedule_ids",
            "created_at",
            'is_show_on_home_page',
            'is_active',
            'instructor',
            'instructor_name'
        ]
    
    def get_instructor_name(self, obj):
        if obj.instructor:
            # Try to get the related InstructorProfile
            profile = getattr(obj.instructor, 'instructor_profile', None)
            if profile:
                return profile.full_name
            # Fallback to email if profile missing
            return obj.instructor.email
        return None


class ClassBookingSerializer(serializers.ModelSerializer):
    class_name = serializers.CharField(source="gym_class.title", read_only=True)
    instructor = serializers.CharField(source="gym_class.instructor.full_name", read_only=True)
    class_duration = serializers.CharField(source="gym_class.class_duration", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)

    schedules = serializers.SerializerMethodField()

    class Meta:
        model = ClassBooking
        fields = "__all__"
        read_only_fields = ("user", "created_at")

    def get_schedules(self, obj):
        return [
            {
                "day": schedule.day,
                "time": schedule.time
            }
            for schedule in obj.gym_class.class_schedule.all()
        ]

# blog

class BlogCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogCategory
        fields = ['id', 'name', 'slug']

class DashboardBlogSerializer(serializers.ModelSerializer):
    # Read category as nested for GET, write as PK for POST/PUT
    category = BlogCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=BlogCategory.objects.all(),
        source='category',
        write_only=True
    )
    image = serializers.ImageField(required=False)  

    class Meta:
        model = Blog
        fields = [
            'id',
            'title',
            'slug',
            'excerpt',
            'description',
            'image',
            'category',
            'category_id',   # this is required for create/update
            'status',
            'is_show_on_home_page',
            # 'meta_title',
            # 'meta_description',
            # 'meta_keywords',
            'author',
            'published_date',
            'created_at',
        ]
        read_only_fields = ['author', 'published_date', 'created_at']

    def create(self, validated_data):
        # Assign author automatically
        validated_data['author'] = self.context['request'].user

        # Set published_date if status is published
        if validated_data.get('status') == 'published':
            validated_data['published_date'] = timezone.now()

        return super().create(validated_data)

    def update(self, instance, validated_data):
        if validated_data.get('status') == 'published' and not instance.published_date:
            validated_data['published_date'] = timezone.now()
        return super().update(instance, validated_data)

class BlogListSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer()
    # category = serializers.PrimaryKeyRelatedField(
    #     queryset=BlogCategory.objects.all()
    # )

    class Meta:
        model = Blog
        fields = [
            'id',
            'title',
            'slug',
            'image',
            'category',
            'status',
            'published_date',
            'created_at',
            'excerpt',
        ]


class BlogDetailSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer()

    class Meta:
        model = Blog
        fields = '__all__'


# --- Contact Serializer.

class ContactCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "preferred_club",
            "subject",
            "message",
        ]


class ContactDashboardSerializer(serializers.ModelSerializer):
    preferred_club_name = serializers.CharField(
        source="preferred_club.name",
        read_only=True
    )

    class Meta:
        model = Contact
        fields = "__all__"


# --- FitHive Support Serializer.
class FitHiveSupportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FitHiveSupport
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "interested_in",
        ]


class FitHiveSupportDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = FitHiveSupport
        fields = "__all__"

# Fithive contact serializer
class FitHiveSupportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FitHiveSupport
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "interested_in",
        ]

# Fithive support dashboard serializer
class FitHiveSupportDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = FitHiveSupport
        fields = "__all__"


# -- package manager --
class PackageFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageFeature
        fields = ['id', 'feature']

class PackageAddOnSerializer(serializers.ModelSerializer):
    class Meta:
        model = PackageAddOn
        fields = ['id', 'name', 'price', 'description', 'is_active']

class PackageSerializer(serializers.ModelSerializer):
    features = PackageFeatureSerializer(many=True)
    addons = PackageAddOnSerializer(many=True)

    class Meta:
        model = Package
        fields = [
            'id',
            'name',
            'duration',
            'price',
            'display_order',
            'description',
            'is_popular',
            'is_active',
            'features',
            'addons',
        ]

    def create(self, validated_data):
        features_data = validated_data.pop('features', [])
        addons_data = validated_data.pop('addons', [])

        package = Package.objects.create(**validated_data)

        # Create features
        for feature in features_data:
            PackageFeature.objects.create(
                package=package,
                feature=feature['feature']
            )

        # Create addons
        for addon in addons_data:
            PackageAddOn.objects.create(
                package=package,
                name=addon['name'],
                price=addon['price'],
                description=addon.get('description', ''),
                is_active=addon.get('is_active', True)
            )

        return package

    def update(self, instance, validated_data):
        features_data = validated_data.pop('features', [])
        addons_data = validated_data.pop('addons', [])

        # Update main package fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        #  Replace features
        instance.features.all().delete()
        for feature in features_data:
            PackageFeature.objects.create(
                package=instance,
                feature=feature['feature']
            )

        #  Replace addons
        instance.addons.all().delete()
        for addon in addons_data:
            PackageAddOn.objects.create(
                package=instance,
                name=addon['name'],
                price=addon['price'],
                description=addon.get('description', ''),
                is_active=addon.get('is_active', True)
            )

        return instance