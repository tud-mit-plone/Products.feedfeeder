# -*- coding: utf-8 -*-
from bs4 import BeautifulSoup
from httplib import InvalidURL
from DateTime import DateTime
from DateTime.interfaces import SyntaxError as DateTimeSyntaxError
from hashlib import md5
from HTMLParser import HTMLParseError
from Products.CMFCore.utils import getToolByName
from Products.feedfeeder.config import MAXSIZE
from Products.feedfeeder.events import FeedItemConsumedEvent
from Products.feedfeeder.extendeddatetime import extendedDateTime
from Products.feedfeeder.interfaces.consumer import IFeedConsumer
from Products.feedfeeder.interfaces.container import IFeedsContainer
from Products.feedfeeder.interfaces.contenthandler import IFeedItemContentHandler  # noqa
from xml.dom import minidom
from zope import component
from zope import event
from zope import interface

import feedparser
import transaction
import logging
import os
import re
import tempfile
import urllib2


RE_FILENAME = re.compile('filename *= *(.*)')
logger = logging.getLogger("feedfeeder")


# Unifiable list taken from http://www.aaronsw.com/2002/html2text.py
unifiable = {
    'rsquo': "'", 'lsquo': "'", 'rdquo': '"', 'ldquo': '"', 'nbsp': ' ',
    'rarr': '->', 'larr': '<-', 'middot': '*', 'copy': '(C)',
    'mdash': '--', 'ndash': '-', 'oelig': 'oe', 'aelig': 'ae',
    'agrave': 'a', 'aacute': 'a', 'acirc': 'a', 'atilde': 'a', 'auml': 'a',
    'aring': 'a',
    'egrave': 'e', 'eacute': 'e', 'ecirc': 'e', 'euml': 'e',
    'igrave': 'i', 'iacute': 'i', 'icirc': 'i', 'iuml': 'i',
    'ograve': 'o', 'oacute': 'o', 'ocirc': 'o', 'otilde': 'o', 'ouml': 'o',
    'ugrave': 'u', 'uacute': 'u', 'ucirc': 'u', 'uuml': 'u',
}


def convert_summary(input):
    try:
        soup = BeautifulSoup(input, "html.parser")
        value = soup.decode(formatter="minimal")
    except HTMLParseError:
        return input
    return value


def update_text(obj, text, mimetype=None, no_reindex=False):
    field = obj.getField('text')
    if mimetype in field.getAllowedContentTypes(obj):
        obj.setText(text, mimetype=mimetype)
        if not no_reindex:
            obj.reindexObject()
    else:
        # update does a reindexObject automatically
        obj.update(text=text)


def get_uid_from_entry(entry):
    """Get a unique id from the entry.

    We return an md5 digest.  Usually that should be from the id of
    the entry, but sometimes, rss providers send items without guid
    element; we take the link then.

    Surprisingly, these are optional, at least in rss, so we take the
    title then.
    """
    if hasattr(entry, 'id'):
        value = entry.id
    elif hasattr(entry, 'link'):
        value = entry.link
    elif hasattr(entry, 'title'):
        value = entry.title
    else:
        return None
    sig = md5(value.encode('ascii', 'ignore'))
    return sig.hexdigest()


class FeedConsumer:
    """
    """
    # zope3 interfaces
    interface.implements(IFeedConsumer)

    def retrieveFeedItems(self, container):
        feedContainer = IFeedsContainer(container)
        for url in feedContainer.getFeeds():
            self._retrieveSingleFeed(feedContainer, url)

    def tryRenamingEnclosure(self, enclosure, feeditem):
        newId = enclosure.Title()
        for x in range(1, 10):
            if newId not in feeditem.objectIds():
                try:
                    feeditem.manage_renameObject(enclosure.getId(),
                                                 newId)
                    break
                except:
                    pass
            newId = '%i_%s' % (x, enclosure.Title())

    def _retrieveSingleFeed(self, feedContainer, url):
        # check if user whats to add a prefix to link title
        urlinfo = url.split('|')
        if len(urlinfo) > 1:
            prefix = urlinfo[0]
            if prefix[-1] != ' ':
                prefix += u' '
            url = urlinfo[1]
        else:
            prefix = ''
        # feedparser doesn't understand proper file: url's
        if url.startswith('file://'):
            url = url[7:]
            if not os.path.exists(url):
                raise IOError("Couldn't locate %r" % url)
        # urllib does not support the 'feed' scheme -- replace with 'http'
        if url.startswith('feed://'):
            url = url.replace('feed://', 'http://', 1)
        portal_transforms = getToolByName(feedContainer, 'portal_transforms')
        parsed = feedparser.parse(url)
        # get the limit setting from the container to limit number of potential updates and reindexing
        limit = feedContainer.getItemUpdateLimit()
        for entry in parsed.entries[:limit]:
            id = get_uid_from_entry(entry)
            if not id:
                logger.warn("Ignored unidentifiable entry without id or link.")
                continue
            updated = entry.get('updated')
            published = entry.get('published')

            if not updated:
                # property may be blank if item has never
                # been updated -- use published date
                updated = published

            if updated:
                try:
                    updated = extendedDateTime(updated)
                except DateTimeSyntaxError:
                    logger.warn("SyntaxError while parsing %r as DateTime for "
                                "the 'updated' field of entry %s",
                                updated, getattr(entry, 'title', '').encode(
                                    "utf-8"))
                    continue

            prev = feedContainer.getItem(id)
            if prev is None:
                # Completely new item, add it.
                addItem = feedContainer.addItem
            elif updated is None:
                logger.warn("No updated or published date known. "
                            "Not updating previously added entry: {0}".format(
                                getattr(entry, 'title', '').encode("utf-8")))
                continue
            elif updated > prev.getFeedItemUpdated():
                # Refreshed item, replace it.
                addItem = feedContainer.replaceItem
            else:
                # Not new, not refreshed: let it be, laddy.  Still,
                # the entry might have changed slightly, so we check
                # this.
                if prev.getObjectInfo() != entry:
                    # Note: no need for a reindexObject here, which
                    # would also update the modification date, which
                    # we do not want.  See
                    # http://plone.org/products/feedfeeder/issues/34
                    prev.setObjectInfo(entry.copy())
                continue

            obj = addItem(id)

            linkDict = getattr(entry, 'link', None)
            if linkDict:
                # Hey, that's not a dict at all; at least not in my test.
                # link = linkDict['href']
                link = linkDict
            else:
                linkDict = getattr(entry, 'links', [{'href': ''}])[0]
                if 'href' in linkDict:
                    link = linkDict['href']
                else:
                    logger.warn(
                        "No href in linkDict: {0} for entry: {1}"
                        .format(linkDict, getattr(entry, 'title', '').encode(
                            "utf-8")))
                    continue

            if not updated:
                updated = DateTime()
            if published is not None:
                try:
                    published = extendedDateTime(published)
                except DateTimeSyntaxError:
                    logger.warn(
                        "SyntaxError while parsing %r as DateTime for "
                        "the 'published' field of entry %s",
                        published, getattr(entry, 'title', '').encode("utf-8"))
                    continue
                obj.setEffectiveDate(published)

            summary = getattr(entry, 'summary', '')
            logger.debug("1 summary: %r" % summary.encode("utf-8"))
            summary = convert_summary(summary)
            logger.debug("2 summary: %r" % summary.encode("utf-8"))

            obj.update(id=id,
                       title=u"{0}{1}".format(
                           prefix,
                           getattr(
                               entry,
                               'title',
                               '')),
                       description=summary,
                       feedItemAuthor=getattr(entry, 'author', ''),
                       feedItemUpdated=updated,
                       link=link,
                       feedTitle=parsed['feed'].get('title', ''),
                       objectInfo=entry.copy(),
                       )
            # Tags cannot be handled by the update method AFAIK,
            # because it is not an Archetypes field.
            feed_tags = [x.get('term') for x in entry.get('tags', [])]
            obj.feed_tags = feed_tags
            content = None
            if hasattr(entry, 'content'):
                content = entry.content[0]
                ctype = content.get('type')  # sometimes no type on linux prsr.
            elif hasattr(entry, 'summary_detail'):
                # If it is a rss feed with a html description use that
                # as content.
                ctype = entry.summary_detail.get('type')
                if ctype in ('text/xhtml', 'application/xhtml+xml',
                             'text/html'):
                    content = entry.summary_detail
            if content:
                if ctype in ('text/xhtml', 'application/xhtml+xml'):
                    # Archetypes doesn't make a difference between
                    # html and xhtml, so we set the type to text/html:
                    ctype = 'text/html'
                    # Warning: minidom.parseString needs a byte
                    # string, not a unicode one, so we need to
                    # encode it first, but only for this parsing.
                    # http://evanjones.ca/python-utf8.html
                    encoded_content = content['value'].encode('utf-8')
                    try:
                        doc = minidom.parseString(encoded_content)
                    except:
                        # Might be an ExpatError, but that is
                        # somewhere in a .so file, so we cannot
                        # specifically catch only that error.  One
                        # reason for an ExpatError, is that if there
                        # is no encapsulated tag, minidom parse fails,
                        # so we can try again in that case.
                        encoded_content = "<div>" + encoded_content + "</div>"
                        try:
                            doc = minidom.parseString(encoded_content)
                        except:
                            # Might be that ExpatError again.
                            logger.warn(
                                "Error parsing content for %s",
                                id.encode("utf-8"))
                            continue
                    if len(doc.childNodes) > 0 and \
                            doc.firstChild.hasAttributes():
                        handler = None
                        top = doc.firstChild
                        cls = top.getAttribute('class')
                        if cls:
                            handler = component.queryAdapter(
                                obj, IFeedItemContentHandler, name=cls)
                        if handler is None:
                            handler = component.queryAdapter(
                                obj, IFeedItemContentHandler)

                        if handler is None:
                            update_text(obj, content['value'], mimetype=ctype, no_reindex=True)
                        else:
                            handler.apply(top)
                            # Grab the first non-<dl> node and treat
                            # that as the content.
                            actualContent = None
                            for node in top.childNodes:
                                if node.nodeName == 'div':
                                    actualContent = node.toxml()
                                    update_text(obj, actualContent,
                                                mimetype=ctype, no_reindex=True)
                                    break
                    else:
                        update_text(obj, content['value'], mimetype=ctype, no_reindex=True)
                else:
                    update_text(obj, content['value'], mimetype=ctype, no_reindex=True)
                if summary == convert_summary(content['value']):
                    # summary and content is the same so we can cut
                    # the summary.  The transform can stumble over
                    # unicode, so we convert to a utf-8 string.
                    summary = summary.encode('utf-8')
                    if portal_transforms is not None:
                        data = portal_transforms.convert(
                            'html_to_text',
                            summary)
                        summary = data.getData()
                    words = summary.split()[:72]
                    summarywords = words[:45]
                    if len(words) > 70:
                        # use the first 50-70 words as a description
                        for word in words[45:]:
                            summarywords.append(word)
                            if word.endswith('.'):
                                # if we encounter a fullstop that will be the
                                # last word appended to the description
                                break
                        summary = ' '.join(summarywords)
                        if not summary.endswith('.'):
                            summary = summary + ' ...'
                    obj.setDescription(summary)
            if hasattr(entry, 'links'):
                enclosures = [x for x in entry.links if x.rel == 'enclosure']
                real_enclosures = [x for x in enclosures if
                                   not self.isHTMLEnclosure(x)]
                for link in real_enclosures:
                    if MAXSIZE > 0:
                        length = link.get('length', 0)
                        if isinstance(length, basestring):
                            if length.isdigit():
                                length = int(length)
                            else:
                                length = 0
                        if length > MAXSIZE * 1000:
                            logger.warn(
                                "Ignored enclosure {0} size {1} kb exceeds "
                                "maximum {2} kb".format(
                                    link.get('href', ''),
                                    length / 1000, MAXSIZE))
                            continue
                    if not link.get('href', False):
                        continue
                    # to maintain compatibility with previous versions
                    # of feedfeeder ( would create a new enclosure
                    # because the signature has changed if always
                    # using utf-8)
                    try:
                        enclosureSig = md5(link.href)
                    except UnicodeEncodeError:
                        enclosureSig = md5(link.href.encode('utf-8'))
                    enclosureId = enclosureSig.hexdigest()
                    if enclosureId in obj.objectIds():
                        # Two enclosures with the same href in this
                        # entry...
                        continue
                    enclosure = obj.addEnclosure(enclosureId)
                    enclosure.update(title=enclosureId)
                    try:
                        updateWithRemoteFile(enclosure, link)
                        if enclosure.Title() != enclosure.getId():
                            self.tryRenamingEnclosure(enclosure, obj)
                        # At this moment in time, the
                        # rename-after-creation magic might have changed
                        # the ID of the file. So we recatalog the object.
                    except InvalidURL:
                        pass

            if obj is not None:
                # only at the end, we reindex once
                obj.reindexObject()
                # it is only feeds, commit whenever you can
                transaction.commit()
                try:
                    event.notify(FeedItemConsumedEvent(obj))
                except UnicodeDecodeError:
                    logger.warn("UnicodeDecodeError: %s" %
                                '/'.join(obj.getPhysicalPath()))

    def isHTMLEnclosure(self, enclosure):
        if hasattr(enclosure, 'type'):
            return enclosure.type == u'text/html'
        return False


def updateWithRemoteFile(obj, link):
    file = tempfile.TemporaryFile('w+b')
    try:
        remote = urllib2.urlopen(link.href.encode('utf-8'))
        info = remote.info()
        filename = None
        if link.href.startswith('file:'):
            pos = link.href.rfind('/')
            if pos > -1:
                filename = link.href[pos + 1:]
            else:
                filename = link.href[5:]

        disp = info.get('Content-Disposition', None)
        if disp is not None:
            m = RE_FILENAME.search(disp)
            if m is not None:
                filename = m.group(1).strip()

        if int(info.get('content-length', 0)) > MAXSIZE * 1000:
            logger.warn(
                "Ignored enclosure {0}, size {1} kb exceeds maximum "
                "{2} kb".format(
                    link.get('href', ''),
                    int(info.get('content-length', 0)) / 1000,
                    MAXSIZE))
            return
        if filename is not None:
            obj.update(title=filename)

        max = 2048
        sz = max
        while sz == max:
            buffer = remote.read(max)
            sz = len(buffer)
            if sz > 0:
                file.write(buffer)

        file.flush()
        file.seek(0)
        try:
            link_type = link.type
        except AttributeError:
            # Some links do not have a type.
            # http://plone.org/products/feedfeeder/issues/39
            link_type = 'application/octet-stream'
        obj.update_data(file, link_type)
        file.close()
    except urllib2.URLError:
        # well, if we cannot retrieve the data, the file object will
        # remain empty
        pass
    except OSError:
        # well, if we cannot retrieve the data, the file object will
        # remain empty
        pass


def feedfolder_created_handler(feedfolder, event):
    """Update feed folder after its creation"""
    feedfolder.restrictedTraverse("update_feed_items")()
