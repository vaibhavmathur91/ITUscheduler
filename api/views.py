import requests
import re
from bs4 import BeautifulSoup
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import generic
from api.models import MajorCode, Course, Lecture, Prerequisite, MajorRestriction
from scheduler.models import Schedule, Notification
from django.utils import timezone
from django.core.mail import send_mail

BASE_URL = "http://www.sis.itu.edu.tr/tr/ders_programlari/LSprogramlar/prg.php?fb="


def notify_course_removal(course):
    schedules = course.schedule_set.all()
    users = list(set([schedule.user for schedule in schedules]))

    for user in users:
        notification = Notification()
        notification.user = user
        notification.msg = 'Course #{} in your schedule #{} has been removed from ITU SIS. Please update your schedule according to the new changes.\n\nITUscheduler loves you.'.format(course.crn, ", #".join([str(schedule.id) for schedule in schedules]))
        notification.save()
        recipients = [user.email, 'info@ituscheduler.com', 'dorukgezici96@gmail.com', 'altunerism@gmail.com']
        send_mail(
            '[ITUscheduler] | Course #{} is Removed'.format(course.crn),
            '\tCourse #{} in your schedule #{} has been removed from ITU SIS. Please update your schedule according to the new changes.\n\nITUscheduler loves you.'.format(
                course.crn, ", #".join([str(schedule.id) for schedule in schedules])),
            'info@ituscheduler.com',
            recipients,
        )


class RefreshCoursesView(UserPassesTestMixin, generic.ListView):
    model = MajorCode
    template_name = "refresh_courses.html"

    def test_func(self):
        if self.request.user.is_superuser:
            return True
        else:
            return False


@user_passes_test(lambda u: u.is_superuser)
def db_refresh_major_codes(request):
    r = requests.get(BASE_URL)
    soup = BeautifulSoup(r.content, "html.parser")
    codes = [major_code.code for major_code in MajorCode.objects.all()]

    for option in soup.find("select").find_all("option"):
        if option.attrs["value"] != "":
            opt = option.get_text()[:-1:]
            if opt in codes:
                codes.remove(opt)
            query = MajorCode.objects.filter(code=opt)
            if not query.exists():
                MajorCode.objects.create(code=opt)

    if soup.find("select").find_all("option"):
        for code in codes:
            major_code = MajorCode.objects.get(code=code)
            major_code.delete()
    return HttpResponse("<a href='/'><h1>Major Codes refreshed!</h1></a>")


@user_passes_test(lambda u: u.is_superuser)
def db_refresh_courses(request):
    codes = request.POST.getlist("major_codes[]")
    with transaction.atomic():
        for code in codes:
            major_code = get_object_or_404(MajorCode, code=code)
            crns = [course.crn for course in Course.objects.filter(major_code=code)]
            active_crns = [course.crn for course in Course.objects.active().filter(major_code=code)]

            r = requests.get(BASE_URL + code)
            soup = BeautifulSoup(r.content, "html5lib")
            raw_table = soup.find("table", class_="dersprg")

            nth_course = 3
            new_crns = []
            while True:
                try:
                    raw_course = raw_table.select_one("tr:nth-of-type({})".format(nth_course))
                    if raw_course is None:
                        break
                    try:
                        data = [row.get_text() for row in raw_course.find_all("td")]
                        rows = raw_course.find_all("td")

                        buildings_raw = rows[4].contents[0].contents
                        buildings = []
                        length = len(buildings_raw) // 2
                        for i in range(length):
                            buildings.append(rows[4].contents[0].contents[2 * i])
                        lecture_count = len(buildings)
                        # buildings = [data[4][3 * i:3 * i + 3:] for i in range(lecture_count)]
                        # lecture_count = len(data[4]) // 3

                        crn = int(data[0])
                        new_crns.append(crn)
                        times_start = ""
                        times_finish = ""
                        for index in range(lecture_count):

                            time = data[6][:-1:].split()[index].split("/")

                            if "" in time or "----" in time:
                                time = ["2500", "2500"]
                            for i in range(2):
                                if time[i][0] == "0":
                                    time[i] = time[i][1::]

                            times_start += time[0] + ","
                            times_finish += time[1] + ","

                        times_start = times_start[:-1:]
                        times_finish = times_finish[:-1:]

                        days = data[5].split()
                        majors = data[11].split(", ")

                        prerequisites = re.sub("veya", " or", data[12])
                        prerequisites.replace("(", "")
                        prerequisites.replace(")", "")

                        prerequisites_objects = []
                        if 'Yok/None' not in prerequisites and 'Diğer Şartlar' not in prerequisites and "Özel" not in prerequisites:
                            for prerequisite in prerequisites.split(' or '):
                                prerequisite = prerequisite.split()
                                course = " ".join([str(prerequisite) for prerequisite in prerequisite[:2]])
                                grade = str(prerequisite[-1])

                                prerequisites_objects.append(Prerequisite.objects.get_or_create(code=course, min_grade=grade)[0])

                        if crn in crns:
                            course = Course.objects.get(crn=crn)
                            course.lecture_count = lecture_count
                            course.major_code = major_code
                            course.code = data[1]
                            course.catalogue = rows[1].contents[0]["href"]
                            course.title = data[2]
                            course.instructor = data[3]
                            course.capacity = int(data[8])
                            course.enrolled = int(data[9])
                            course.reservation = data[10]
                            course.class_restriction = data[13]
                            course.active = True

                            course.save()

                            for lecture in course.lecture_set.all():
                                lecture.delete()
                        else:
                            course = Course.objects.create(
                                lecture_count=lecture_count,
                                major_code=major_code,
                                crn=crn,
                                catalogue=rows[1].contents[0]["href"],
                                code=data[1],
                                title=data[2],
                                instructor=data[3],
                                capacity=int(data[8]),
                                enrolled=int(data[9]),
                                reservation=data[10],
                                class_restriction=data[13]
                            )

                        for i in range(lecture_count):
                            time_start = times_start.split(",")[i]
                            time_finish = times_finish.split(",")[i]

                            Lecture.objects.create(
                                building=buildings[i],
                                day=days[i],
                                time_start=time_start,
                                time_finish=time_finish,
                                room=data[7].split()[i],
                                course=course
                            )

                        for old_major in course.major_restriction.all():
                            course.major_restriction.remove(old_major)

                        for major in majors:
                            major_restriction, _ = MajorRestriction.objects.get_or_create(major=major)
                            course.major_restriction.add(major_restriction.major)

                        for prerequisite in prerequisites_objects:
                            course.prerequisites.add(prerequisite.id)

                        course.save()
                        nth_course += 1
                    except AttributeError:
                        nth_course += 1
                except IndexError:
                    break

            removed_crns = [crn for crn in active_crns if crn not in new_crns]
            for removed_crn in removed_crns:
                old_course = Course.objects.active().get(crn=removed_crn)
                notify_course_removal(old_course)
                old_course.active = False
                old_course.save()
                print("Course {} is removed from ITU SIS.".format(old_course))

            major_code.refreshed = timezone.now()
            major_code.save()
    return HttpResponse("<a href='/api/refresh/courses'><h1>{} Courses refreshed!</h1></a>".format(", ".join(codes)))


class FlushView(UserPassesTestMixin, generic.TemplateView):
    model = MajorCode
    template_name = "flush.html"

    def test_func(self):
        if self.request.user.is_superuser:
            return True
        else:
            return False


@user_passes_test(lambda u: u.is_superuser)
def db_flush(request):
    MajorCode.objects.all().delete()
    Course.objects.all().delete()
    Schedule.objects.all().delete()

    return HttpResponse("<a href='/'><h1>Major Codes and Courses flushed!</h1></a>")
