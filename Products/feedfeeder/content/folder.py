# -*- coding: utf-8 -*-
from AccessControl import ClassSecurityInfo
from Products.Archetypes import atapi
from Products.ATContentTypes.content.folder import ATBTreeFolder
from Products.CMFCore.utils import getToolByName
from Products.feedfeeder import _
from Products.feedfeeder.config import PROJECTNAME
from Products.feedfeeder.interfaces.container import IFeedsContainer
from zope import interface


schema = atapi.Schema((

    atapi.LinesField(
        name='feeds',
        widget=atapi.LinesWidget(
            description=_(
                "help_feeds",
                default="List of rss feeds. You can prefix feed link titles "
                "using | separator. It is probably a good idea to add a colon "
                "or dash at the end of the prefix "
                "('My place: |http://myplace/feed')."),
            label=_('feedfeeder_label_feeds', default='Feeds')
        )
    ),

    atapi.BooleanField(
        name='redirect',
        widget=atapi.BooleanWidget(
            description=_(
                "help_redirect",
                default="If checked the feed item will be automatically "
                "redirected if you don't have the edit permission."),
            label=_(
                'label_redirect',
                default='Automatic redirect of feed items')
        )
    ),

    atapi.StringField(
        name='defaultTransition',
        vocabulary='getAvailableTransitions',
        default='publish',
        widget=atapi.SelectionWidget(
            format='select',
            description=_(
                'help_default_transition',
                default="When updating this feed's item the transition "
                "selected below will be performed."),
            label=_('label_default_transition', default='Default transition'),
        )
    ),

    atapi.BooleanField(
        "showURLasSubline",
        default=False,
        schemata="default",
        widget=atapi.BooleanWidget(
            description=_(
                u"help_url_as_subline",
                default=u"Show URL (domain) instead of feed title as source label. Use it for feeds with more than one source.",
            ),
            label=_("label_url_as_subline", default=u"Show URL as Subline"),
        ),
    ),

    atapi.IntegerField(
        "itemUpdateLimit",
        default=20,
        schemata="default",
        widget=atapi.IntegerWidget(
            description=_(
                "help_item_update_limit",
                default=u"Change the limit to allow more (or less) items to be updated when feed update is performed.",
            ),
            label=_("label_item_update_limit", default=u"Feed item limit for feed update")
        )
    ),
),)

FeedfeederFolder_schema = ATBTreeFolder.schema.copy() + \
    schema.copy()

hidden_fields = [
    "allowDiscussion",
    "location",
    "rights",
    "subject",
    "contributors",
    "language",
    "excludeFromNav",
    "defaultTransition",
    "redirect",
]
for field in hidden_fields:
    if field in FeedfeederFolder_schema:
        FeedfeederFolder_schema[field].widget.visible = {"edit": "invisible", "view": "invisible"}


class FeedfeederFolder(ATBTreeFolder):
    """
      Verify class test
      >>> from zope.interface.verify import verifyClass
      >>> verifyClass(IFeedsContainer, FeedfeederFolder)
      True
    """
    security = ClassSecurityInfo()
    # zope3 interfaces
    interface.implements(IFeedsContainer)

    _at_rename_after_creation = True

    schema = FeedfeederFolder_schema

    def getAvailableTransitions(self):
        # Create a temporary object so we can ask what transitions are
        # available for it.
        id = 'temp_zest_temp'
        self.invokeFactory('FeedFeederItem', id)
        wf_tool = getToolByName(self, 'portal_workflow')
        transitions = wf_tool.getTransitionsFor(self[id])
        display_trans = [('', _('Keep initial state')), ]
        for trans in transitions:
            display_trans.append((trans['id'], trans['name']))
        # Unindex and remove the temporary object
        self[id].unindexObject()
        self._delOb(id)
        return atapi.DisplayList(display_trans)

    security.declarePublic('getItem')

    def getItem(self, id):
        """
        """
        if id in self.objectIds():
            return self[id]
        return None

    security.declarePublic('getFeeds')

    def getFeeds(self):
        """
        """
        return self.feeds

    security.declarePublic('replaceItem')

    def replaceItem(self, id):
        """
        """
        self.manage_delObjects([id])
        return self.addItem(id)

    security.declarePublic('addItem')

    def addItem(self, id):
        """
        """
        self.invokeFactory('FeedFeederItem', id)
        transition = self.getDefaultTransition()
        if transition != '':
            wf_tool = getToolByName(self, 'portal_workflow')
            wf_tool.doActionFor(
                self[id], transition,
                comment=_('Automatic transition triggered by FeedFolder'))
        return self[id]

    security.declarePublic('getFeedFolder')

    def getFeedFolder(self):
        return self


atapi.registerType(FeedfeederFolder, PROJECTNAME)
