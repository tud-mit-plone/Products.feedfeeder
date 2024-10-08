# -*- coding: utf-8 -*-
from urlparse import urlparse

from AccessControl import ClassSecurityInfo
from Acquisition import aq_parent
from DateTime import DateTime
from Products.Archetypes import atapi
from Products.ATContentTypes.content.document import ATDocument
from Products.ATContentTypes.content.folder import ATFolder
from Products.CMFCore.utils import getToolByName
from Products.CMFPlone.utils import base_hasattr
from Products.CMFPlone.utils import safe_unicode
from Products.feedfeeder import _
from Products.feedfeeder.config import PROJECTNAME
from Products.feedfeeder.interfaces.item import IFeedItem
from zope import interface


copied_fields = {}
copied_fields['text'] = ATDocument.schema['text'].copy()
copied_fields['text'].required = 0
schema = atapi.Schema((

    atapi.StringField(
        name='feedItemAuthor',
        widget=atapi.StringWidget(
            label=_(
                'feedfeeder_label_feedItemAuthor',
                default='Feeditemauthor'),
        )
    ),

    atapi.DateTimeField(
        name='feedItemUpdated',
        default=DateTime('2000/01/01'),
        widget=atapi.CalendarWidget(
            label=_('feedfeeder_label_feedItemUpdated', 'Feeditemupdated'),
        )
    ),

    copied_fields['text'],
    atapi.StringField(
        name='link',
        widget=atapi.StringWidget(
            label=_('feedfeeder_label_link', default='Link'),
        )
    ),

    atapi.ComputedField(
        name='objectids',
        widget=atapi.ComputedWidget(
            label=_('feedfeeder_label_objectids', default='Object Ids'),
        )
    ),

    atapi.ComputedField(
        name='hasBody',
        widget=atapi.ComputedWidget(
            label=_('feedfeeder_label_hasbody', default='Has body text'),
        )
    ),

    atapi.StringField(
        name='feedTitle',
        widget=atapi.StringWidget(
            label=_('feedfeeder_label_feedTitle', default='Feed Title'),
        )
    ),
    atapi.ObjectField(
        name='objectInfo',
        #        read_permission=ManagePortal,
        #        write_permission=ManagePortal,
        widget=atapi.StringWidget(
            visible={'view': 'invisible',
                     'edit': 'invisible'},
        ),
        default={},
    ),

),
)

FeedFeederItem_schema = getattr(ATFolder, 'schema', atapi.Schema(())).copy() + \
    schema.copy()

hidden_fields = [
    "allowDiscussion",
    "relatedItems",
    "location",
    "rights",
    "subject",
    "contributors",
    "language",
    "excludeFromNav",
]
for field in hidden_fields:
    if field in FeedFeederItem_schema:
        FeedFeederItem_schema[field].widget.visible = {"edit": "invisible", "view": "invisible"}


class FeedFeederItem(ATFolder):
    """
    """
    security = ClassSecurityInfo()
    # zope3 interfaces
    interface.implements(IFeedItem)

    _at_rename_after_creation = True

    schema = FeedFeederItem_schema

    security.declarePublic('getTeaserText')

    def getTeaserText(self):
        """gets text for teaser

        :return: Teaser text
        :rtype: str
        """

        teaser = u""
        # get description from feed item
        description = self.getField("description").get(self)
        # catch empty description
        if description:
            teaser = safe_unicode(description, "utf-8")
        return teaser

    def getSubline(self):
        """gets name of rss feed or url (depending on settings)

        :return: Subline
        :rtype: str
        """
        parent = aq_parent(self)
        showURL = parent.getField("showURLasSubline").get(parent)

        if showURL:
            link = self.getField("link").get(self)
            try:
                parse_result = urlparse(link)
            except Exception:
                return None
            title = parse_result.netloc
            if title.startswith("www."):
                title = title.replace("www.", "")

        else:
            title = parent.getField("title").get(parent)

        source = self.translate(_("teaser_source", default=u"Source"))
        subline = "{source}: {title}".format(source=source, title=title)

        return subline

    security.declarePublic('addEnclosure')

    def addEnclosure(self, id):
        """
        """
        self.invokeFactory('File', id)
        self.reindexObject()
        transition = self.getDefaultTransition()
        if transition != '':
            wf_tool = getToolByName(self, 'portal_workflow')
            # The default transition should be valid for a
            # FeedFolderItem, but our File might not have the same
            # transitions available.  So check this.
            transitions = wf_tool.getTransitionsFor(self[id])
            transition_ids = [trans['id'] for trans in transitions]
            if transition in transition_ids:
                wf_tool.doActionFor(
                    self[id], transition,
                    comment=_('Automatic transition triggered by FeedFolder'))
        return self[id]

    security.declarePublic('remote_url')

    def remote_url(self):
        """Compatibility method that makes working with link checkers
        easier.
        """
        return self.getLink()

    security.declarePublic('getObjectids')

    def getObjectids(self):
        """Return the ids of enclosed objects.
        """
        return self.objectIds()

    security.declarePublic('getHasBody')

    def getHasBody(self):
        """Return True if the object has body text.
        """
        if bool(self.getRawText()):
            return 1
        return 0

    def _get_feed_tags(self):
        """Get the tags from the feed item.

        tags/keywords/categories

        We store this in the _feed_tags attribute.  Old items may not
        have this yet, so we protect against AttributeErrors by
        specifying a getter and setter as wrapper around that
        attribute.  We return an empty list when the attribute is not
        there.

        This is not hooked up yet, but this way the tags are available
        for whoever wants to integrate them in third party products.
        """
        if base_hasattr(self, '_feed_tags'):
            return getattr(self, '_feed_tags')
        return []

    def _set_feed_tags(self, value):
        """Get the tags from the feed item.

        tags/keywords/categories
        """
        if not value:
            self._feed_tags = []
        elif isinstance(value, list):
            self._feed_tags = value
        elif isinstance(value, tuple):
            self._feed_tags = list(value)
        elif isinstance(value, basestring):
            self._feed_tags = [value]
        else:
            raise ValueError("expected list, tuple or basestring, got %s",
                             type(value))

    feed_tags = property(_get_feed_tags, _set_feed_tags)


atapi.registerType(FeedFeederItem, PROJECTNAME)
