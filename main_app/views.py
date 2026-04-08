from rest_framework.viewsets import ModelViewSet
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import generics
from rest_framework.filters import SearchFilter
from .models import( 
    Banner,
    GymClub,
    GymClass, 
    Category,
    ClassSchedule,
    Blog,
    BlogCategory,
    Contact,
    FitHiveSupport,
    Package
)
from .serializers import (
    BannerSerializer,
    GymClubSerializer,
    GymClassSerializer,
    ClassBookingSerializer,
    CategorySerializer,
    ClassScheduleSerializer,
    BlogListSerializer, 
    BlogDetailSerializer,
    BlogCategorySerializer,
    ContactCreateSerializer,
    FitHiveSupportCreateSerializer,
    PackageSerializer
)

class BannerViewSet(ModelViewSet):
    queryset = Banner.objects.filter(is_active=True)
    serializer_class = BannerSerializer

class GymClubViewSet(ModelViewSet):
    queryset = GymClub.objects.all()
    serializer_class = GymClubSerializer

class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ScheduleListCreateView(generics.ListCreateAPIView):
    queryset = ClassSchedule.objects.all()
    serializer_class = ClassScheduleSerializer

# gym class

class GymClassListCreateView(generics.ListCreateAPIView):
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related("category")
    serializer_class = GymClassSerializer


class GymClassDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = GymClass.objects.prefetch_related("class_schedule").select_related("category")
    serializer_class = GymClassSerializer

# Blog views
class PublicBlogListView(generics.ListAPIView):
    serializer_class = BlogListSerializer
    filter_backends = [SearchFilter]
    search_fields = ['title', 'description', 'category__name']

    def get_queryset(self):
        return Blog.objects.filter(status='published').order_by('-published_date')

class PublicBlogDetailView(generics.RetrieveAPIView):
    serializer_class = BlogDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Blog.objects.filter(status='published')

class BlogCategoryViewSet(ModelViewSet):
    queryset = BlogCategory.objects.all()
    serializer_class = BlogCategorySerializer


# Contact 
class ContactCreateAPIView(generics.CreateAPIView):
    queryset = Contact.objects.all()
    serializer_class = ContactCreateSerializer
    
# Fithive support
class FitHiveSupportCreateAPIView(generics.CreateAPIView):
    queryset = FitHiveSupport.objects.all()
    serializer_class = FitHiveSupportCreateSerializer
   
# package
class PublicPackageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Package.objects.filter(is_active=True).order_by('display_order', 'name')
    serializer_class = PackageSerializer
    permission_classes = [permissions.AllowAny]  # Public endpoint