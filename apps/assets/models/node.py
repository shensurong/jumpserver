# -*- coding: utf-8 -*-
#
import uuid

from django.db import models, transaction
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _

from orgs.mixins import OrgModelMixin
from orgs.utils import current_org, set_current_org, get_current_org
from orgs.models import Organization

__all__ = ['Node']


class Node(OrgModelMixin):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    key = models.CharField(unique=True, max_length=64, verbose_name=_("Key"))  # '1:1:1:1'
    value = models.CharField(max_length=128, verbose_name=_("Value"))
    child_mark = models.IntegerField(default=0)
    date_create = models.DateTimeField(auto_now_add=True)

    is_node = True

    def __str__(self):
        return self.value
        # return self.full_value

    def __eq__(self, other):
        return self.key == other.key

    def __gt__(self, other):
        if self.is_root():
            return True
        self_key = [int(k) for k in self.key.split(':')]
        other_key = [int(k) for k in other.key.split(':')]
        if len(self_key) < len(other_key):
            return True
        elif len(self_key) > len(other_key):
            return False
        else:
            return self_key[-1] < other_key[-1]

    @property
    def name(self):
        return self.value

    @property
    def full_value(self):
        ancestor = [a.value for a in self.get_ancestor(with_self=True)]
        if self.is_root():
            return self.value
        return ' / '.join(ancestor)

    @property
    def level(self):
        return len(self.key.split(':'))

    def get_next_child_key(self):
        mark = self.child_mark
        self.child_mark += 1
        self.save()
        return "{}:{}".format(self.key, mark)

    def create_child(self, value):
        with transaction.atomic():
            child_key = self.get_next_child_key()
            child = self.__class__.objects.create(key=child_key, value=value)
            return child

    def get_children(self, with_self=False):
        pattern = r'^{0}$|^{}:[0-9]+$' if with_self else r'^{}:[0-9]+$'
        return self.__class__.objects.filter(
            key__regex=pattern.format(self.key)
        )

    def get_all_children(self, with_self=False):
        pattern = r'^{0}$|^{0}:' if with_self else r'^{0}'
        return self.__class__.objects.filter(
            key__regex=pattern.format(self.key)
        )

    def get_sibling(self, with_self=False):
        key = ':'.join(self.key.split(':')[:-1])
        pattern = r'^{}:[0-9]+$'.format(key)
        sibling = self.__class__.objects.filter(
            key__regex=pattern.format(self.key)
        )
        if not with_self:
            sibling = sibling.exclude(key=self.key)
        return sibling

    def get_family(self):
        ancestor = self.get_ancestor()
        children = self.get_all_children()
        return [*tuple(ancestor), self, *tuple(children)]

    def get_assets(self):
        from .asset import Asset
        if self.is_root():
            assets = Asset.objects.filter(
                Q(nodes__id=self.id) | Q(nodes__isnull=True)
            )
        else:
            assets = self.assets.all()
        return assets

    def get_valid_assets(self):
        return self.get_assets().valid()

    def get_all_assets(self):
        from .asset import Asset
        pattern = r'^{0}$|^{0}:'.format(self.key)
        args = []
        kwargs = {}
        if self.is_default_node():
            args.append(Q(nodes__key__regex=pattern) | Q(nodes__key=None))
        else:
            kwargs['nodes__key__regex'] = pattern
        assets = Asset.objects.filter(*args, **kwargs)
        return assets

    def get_all_valid_assets(self):
        return self.get_all_assets().valid()

    def is_default_node(self):
        return self.is_root() and self.key == '0'

    def is_root(self):
        if self.key.isdigit():
            return True
        else:
            return False

    @property
    def parent(self):
        if self.is_root():
            return self
        parent_key = ":".join(self.key.split(":")[:-1])
        try:
            parent = self.__class__.objects.get(key=parent_key)
            return parent
        except Node.DoesNotExist:
            return self.__class__.root()

    @parent.setter
    def parent(self, parent):
        if not self.is_node:
            self.key = parent.key + ':fake'
            return
        children = self.get_all_children()
        old_key = self.key
        with transaction.atomic():
            self.key = parent.get_next_child_key()
            for child in children:
                child.key = child.key.replace(old_key, self.key, 1)
                child.save()
            self.save()

    def get_ancestor(self, with_self=False):
        if self.is_root():
            root = self.__class__.root()
            return [root]
        _key = self.key.split(':')
        if not with_self:
            _key.pop()
        ancestor_keys = []
        for i in range(len(_key)):
            ancestor_keys.append(':'.join(_key))
            _key.pop()
        ancestor = self.__class__.objects.filter(
            key__in=ancestor_keys
        ).order_by('key')
        return ancestor

    @classmethod
    def create_root_node(cls):
        # 如果使用current_org 在set_current_org时会死循环
        _current_org = get_current_org()
        with transaction.atomic():
            set_current_org(Organization.root())
            org_nodes_roots = cls.objects.filter(key__regex=r'^[0-9]+$')
            org_nodes_roots_keys = org_nodes_roots.values_list('key', flat=True)
            max_value = max([int(k) for k in org_nodes_roots_keys]) if org_nodes_roots_keys else -1
            set_current_org(_current_org)
            root = cls.objects.create(key=str(max_value+1), value=_current_org.name)
            return root

    @classmethod
    def root(cls):
        root = cls.objects.filter(key__regex=r'^[0-9]+$')
        if root:
            return root[0]
        else:
            return cls.create_root_node()



