from django.views.generic import ListView
from django.core.paginator import Paginator
from .models import Post
from api.models import Course, MajorCode
from scheduler.models import Schedule
from scheduler.models import ExtendedUser


class PostListView(ListView):
    queryset = Post.objects.all()
    context_object_name = 'posts'
    paginate_by = 3
    refresh_paginator = Paginator(MajorCode.objects.all(), 17)

    def get_context_data(self, **kwargs):
        context = super(PostListView, self).get_context_data(**kwargs)
        deleted_courses_count = Course.objects.inactive().count()
        total_schedule_count = Schedule.objects.all().count()
        user_count = ExtendedUser.objects.all().count()

        context["deleted_courses_count"] = deleted_courses_count
        context["total_schedule_count"] = total_schedule_count
        context["user_count"] = user_count

        refresh_page = self.request.GET.get("refresh_page")
        context["refreshes"] = self.refresh_paginator.get_page(refresh_page)

        return context

