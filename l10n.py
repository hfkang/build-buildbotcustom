# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla-specific Buildbot steps.
#
# The Initial Developer of the Original Code is
# Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2007
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Axel Hecht <l10n@mozilla.com>
#   Armen Zambrano Gasparnian <armenzg@mozilla.com>
#   Chris AtLee <catlee@mozilla.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

from twisted.python import log
from twisted.internet import defer
from twisted.web.client import getPage
from buildbot.scheduler import Dependent, Triggerable, Nightly
from buildbot.sourcestamp import SourceStamp
from buildbot.process import properties
from buildbot.status.builder import SUCCESS, WARNINGS


def ParseLocalesFile(data):
    """
    @type  data: string
    @param data: The contents of all-locales or shipped-locales files

    This function creates a dictionary that has locales as the keys
    and the value associated can be a list of platforms for which the
    locale should be repackaged on (think of ja and ja-JP-mac)
    """
    locales = {}
    data = data.strip()
    for line in data.split('\n'):
        splitLine = line.split()
        locale = splitLine[0]
        buildPlatforms = splitLine[1:]
        if locale in locales:
            for plat in buildPlatforms:
                if plat not in locales[locale]:
                    locales[locale].append(plat)
        else:
            locales[locale] = buildPlatforms
    return locales


class L10nMixin(object):
    """
    This class helps any of the L10n custom made schedulers
    to submit BuildSets as specified per list of locales, or either a
    'all-locales' or 'shipped-locales' file via a call to createL10nBuilds.

    For each locale, there will be a build property 'locale' set to the
    inidividual locale to be built for that BuildSet.
    """

    def __init__(self, platform, repo='https://hg.mozilla.org/', branch=None,
                 baseTag='default', localesFile="browser/locales/all-locales",
                 locales=None, localesURL=None):
        """
        You can call this class with either a defined list of locales or
        a URL that contains the list of locales
        """
        self.branch = branch
        self.baseTag = baseTag
        if localesURL:
            self.localesURL = localesURL
        else:
            # Make sure that branch is not none when using this path
            assert branch is not None
            # revision will be expanded later
            self.localesURL = "%s%s/raw-file/%%(revision)s/%s" % \
                (repo, branch, localesFile)

        # if the user wants to use something different than all locales
        # check ParseLocalesFile function to note that we now need a dictionary
        # with the locale as the key and a list of platform as the value for
        # each key to build a specific locale e.g. locales={'fr':['osx']}
        self.locales = locales
        # Make sure a supported platform is passed. Allow variations, but make
        # sure to convert them to the form the locales files ues.
        assert platform in ('linux', 'linux64', 'win32', 'win64',
                            'macosx', 'macosx64', 'osx', 'osx64')

        self.platform = platform
        if self.platform.startswith('macosx'):
            self.platform = 'osx'
        if self.platform.startswith('linux'):
            self.platform = 'linux'

    def _cbLoadedLocales(self, t, locales, reason, set_props):
        """
        This is the callback function that gets called once the list
        of locales are ready to be processed
        Let's fill the queues per builder and submit the BuildSets per each locale
        """
        log.msg("L10nMixin:: loaded locales' list")
        db = self.parent.db
        for locale in locales:
            # Ignore en-US. It appears in locales files but we do not repack
            # it.
            if locale == "en-US":
                continue
            # Some locales should only be built on certain platforms, make sure to
            # obey those rules.
            if len(locales[locale]) > 0:
                if self.platform not in locales[locale]:
                    continue
            props = properties.Properties()
            props.updateFromProperties(self.properties)
            if set_props:
                props.updateFromProperties(set_props)
            # I do not know exactly what to pass as the source parameter
            props.update(dict(locale=locale), "Scheduler")
            props.setProperty("en_revision", self.baseTag, "L10nMixin")
            props.setProperty("l10n_revision", self.baseTag, "L10nMixin")
            log.msg('Submitted ' + locale + ' locale')
            # let's submit the BuildSet for this locale
            # Create a sourcestamp
            ss = SourceStamp(branch=self.branch)
            ssid = db.get_sourcestampid(ss, t)
            self.create_buildset(ssid, reason, t, props=props)

    def getLocales(self, revision=None):
        """
        It returns a list of locales if the user has set a list of locales
        in the scheduler OR it returns a Deferred.

        You want to call this method via defer.maybeDeferred().
        """
        if self.locales:
            log.msg(
                'L10nMixin.getLocales():: The user has set a list of locales')
            return self.locales
        else:
            localePage = self.localesURL % {'revision':
                                            revision or self.baseTag}
            log.msg("L10nMixin:: Getting locales from: " + localePage)
            # we expect that getPage will return the output of "all-locales"
            # or "shipped-locales" or any file that contains a locale per line
            # in the begining of the line e.g. "en-GB" or "ja linux win32"
            # getPage returns a defered that will return a string
            d = getPage(localePage, timeout=5 * 60)
            d.addCallback(lambda data: ParseLocalesFile(data))
            return d

    def createL10nBuilds(self, revision=None, reason=None, set_props=None):
        """
        We request to get the locales that we have to process and which
        method to call once they are ready
        """
        log.msg('L10nMixin:: A list of locales is going to be requested')
        d = defer.maybeDeferred(self.getLocales, revision)
        d.addCallback(lambda locales: self.parent.db.runInteraction(
            self._cbLoadedLocales, locales, reason, set_props))
        return d


class TriggerableL10n(Triggerable, L10nMixin):
    """
    TriggerableL10n is used to paralellize the generation of l10n builds.

    TriggerableL10n is designed to be used with a Build factory that gets the
    locale to build from the 'locale' build property.
    """

    compare_attrs = ('name', 'builderNames', 'branch')

    def __init__(self, name, builderNames, **kwargs):
        L10nMixin.__init__(self, **kwargs)
        Triggerable.__init__(self, name, builderNames)

    def trigger(self, ss, set_props=None):
        reason = "This build was triggered by the successful completion of the en-US nightly."
        self.createL10nBuilds(
            revision=ss.revision, reason=reason, set_props=set_props)
