import unittest

import django
from django.dispatch import receiver
from django.db import models
from django.test import TestCase
from django_fsm import (
    FSMField,
    ConcurrentTransitionMixin,
    ConcurrentTransition,
    transition,
)
from django_fsm.signals import post_transition


class LockedBlogPost(ConcurrentTransitionMixin, models.Model):
    state = FSMField(default="new")
    text = models.CharField(max_length=50)

    @transition(field=state, source="new", target="published")
    def publish(self):
        pass

    @transition(field=state, source="published", target="removed")
    def remove(self):
        pass

    class Meta:
        app_label = "testapp"


class ExtendedBlogPost(LockedBlogPost):
    review_state = FSMField(default="waiting", protected=True)
    notes = models.CharField(max_length=50)

    @transition(field=review_state, source="waiting", target="rejected")
    def reject(self):
        pass

    class Meta:
        app_label = "testapp"


class BlogPostWithPostTransitionHandler(LockedBlogPost):
    review_state = FSMField(default="new", protected=True)
    notes = models.CharField(max_length=50)

    @transition(field=review_state, source="new", target="waiting")
    def submit(self):
        pass

    @transition(field=review_state, source="waiting", target="published")
    def skip_review(self):
        pass

    class Meta:
        app_label = "testapp"


@receiver(post_transition, sender=BlogPostWithPostTransitionHandler)
def handle_post_transition(sender, instance, name, source, target, **kwargs):
    if target == "waiting":
        instance.skip_review()
        # instance.save()


class TestLockMixin(TestCase):
    def test_create_succeed(self):
        LockedBlogPost.objects.create(text="test_create_succeed")

    def test_crud_succeed(self):
        post = LockedBlogPost(text="test_crud_succeed")
        post.publish()
        post.save()

        post = LockedBlogPost.objects.get(pk=post.pk)
        self.assertEqual("published", post.state)
        post.text = "test_crud_succeed2"
        post.save()

        post = LockedBlogPost.objects.get(pk=post.pk)
        self.assertEqual("test_crud_succeed2", post.text)

        post.delete()

    def test_save_and_change_succeed(self):
        post = LockedBlogPost(text="test_crud_succeed")
        post.publish()
        post.save()

        post.remove()
        post.save()

        post.delete()

    def test_concurrent_modifications_raise_exception(self):
        post1 = LockedBlogPost.objects.create()
        post2 = LockedBlogPost.objects.get(pk=post1.pk)

        post1.publish()
        post1.save()

        post2.text = "aaa"
        post2.publish()
        with self.assertRaises(ConcurrentTransition):
            post2.save()

    def test_inheritance_crud_succeed(self):
        post = ExtendedBlogPost(text="test_inheritance_crud_succeed", notes="reject me")
        post.publish()
        post.save()

        post = ExtendedBlogPost.objects.get(pk=post.pk)
        self.assertEqual("published", post.state)
        post.text = "test_inheritance_crud_succeed2"
        post.reject()
        post.save()

        post = ExtendedBlogPost.objects.get(pk=post.pk)
        self.assertEqual("rejected", post.review_state)
        self.assertEqual("test_inheritance_crud_succeed2", post.text)

    @unittest.skipIf(django.VERSION[:3] < (1, 8, 0), "Available on django 1.8+")
    def test_concurrent_modifications_after_refresh_db_succeed(self):  # bug 255
        post1 = LockedBlogPost.objects.create()
        post2 = LockedBlogPost.objects.get(pk=post1.pk)

        post1.publish()
        post1.save()

        post2.refresh_from_db()
        post2.remove()
        post2.save()

    def test_post_transition_calling_another_transition(self):
        post = BlogPostWithPostTransitionHandler.objects.create()
        post.submit()
        post.save()
        self.assertEqual("published", post.review_state)
