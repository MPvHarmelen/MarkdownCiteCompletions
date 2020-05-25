'''
This module implements the cite-completion behaviour, largely by relying on
implementations registered with latextools_plugin and configured using the
`bibliograph_plugins` configuration key.

At present, there is one supported method on custom plugins.

`get_entries`:
    This method should take a sequence of bib_files and return a sequence of
    Mapping-like objects where the key corresponds to a Bib(La)TeX key and
    returns the matching value. We provide default fallbacks for any of the
    quick panel formatting options that might not be automatically mapped to
    a field, e.g., `author_short`, etc. or to deal with missing data, e.g.
    entries that have no `journal` but use the `journaltitle` field. Plugins
    can override this behaviour, however, by explicitly setting a value for
    whatever key they like.
'''
import sublime
from .latextools_utils.kpsewhich import kpsewhich
from .latextools_utils import bibformat
from .latextools_utils.settings import get_setting

import os
import re

import traceback

from .bibliography_plugins import (
    traditionalBibliography,
    newBibliography,
)

REGISTRY = {
    'traditional': traditionalBibliography.TraditionalBibliographyPlugin,
    'new': newBibliography.NewBibliographyPlugin,
}


class NoBibFilesError(Exception):
    pass


class BibParsingError(Exception):

    def __init__(self, filename=""):
        self.filename = filename


class BibPluginError(Exception):
    pass


OLD_STYLE_CITE_REGEX = re.compile(r"([^_]*_)?\*?([a-z]*?)etic\\")
# I apoligise profusely for this regex
# forward version with explanation:
# \\
#    (?:
#       (?#
#           first branch matches \foreigntextquote,
#           \hypentextquote, \foreignblockquote, \hyphenblockquote,
#           \hybridblockquote and starred versions
#           syntax is:
#           \foreigntextquote{lang}[key][punct]{text}
#       )
#       (?:foreign|hyphen|hybrid(?=block))(?:text|block)quote\*?
#           \{[^}]*\}\[(?:(?:[^[\],]*,)*)?|
#       (?#
#           second branch matches \textquote, \blockquote and
#           starred versions
#           syntax is:
#           \textquote[key]{text}
#       )
#       (?:text|block)quote\*?\[(?:(?:[^[\],]*,)*)?|
#       (?#
#           third branch matches \foreigntextcquote,
#           \hyphentextcquote, \foreignblockcquote, \hypenblockcquote,
#           \hybridblockcquote and starred versions
#           syntax is:
#           \foreigntextcquote{lang}[prenote][postnote]{key}{text}
#       )
#       (?:foreign|hyphen|hybrid(?=block))(?:text|block)cquote\*?
#           \{[^}]*\}(?:\[[^\]]*\]){0,2}\{(?:(?:[^{},]*,)*)?|
#       (?#
#           fourth branch matches \textcquote, \blockcquote and
#           starred versions
#           syntax is:
#           \textcquote[prenote][postnote]{key}{text}
#       )
#       (?:text|block)cquote\*?(?:\[[^\]]*\]){0,2}\{(?:(?:[^{},]*,)*)?|
#       (?#
#           fifth branch matches \volcite and friends
#           syntax is:
#           \volcite[prenote]{volume}[page]{key}
#       )
#       (?:p|P|f|ft|s|S|t|T|a|A)?volcite
#           (?:\[[^\]]*\])?\{[^}]*\}(?:\[[^\]]*\])?\{(?:(?:[^{},]*,)*)?|
#       (?#
#           sixth branch matches \volcites and friends
#           syntax is:
#           \volcites(multiprenote)(multipostnote)[prenote]{volume}[page]{key}
#               ...[prenote]{volume}[page]{key}
#       )
#       (?:p|P|f|ft|s|S|t|T|a|A)?volcites
#           (?:\([^)]*\)){0,2}
#               (?:(?:\[[^\]]*\])?\{[^}]*\}
#               (?:\[[^\]]*\])?\{(?:(?:[^{},]*,)*)?(?:\}(?=.*?\{))?){1,}|
#       (?#
#           seventh branch matches \cites and friends, excluding \volcite
#           syntax is:
#           \cites(multiprenote)(multipostnote)[prenote][postnote]{key}
#               ...[prenote][postnote]{key}
#       )
#       (?:(?!(?:p|P|f|ft|s|S|t|T|a|A)?volcites)
#           (?:[A-Z]?[a-z]*c)|C)ites(?!style)
#           (?:\([^)]*\)){0,2}
#           (?:(?:\[[^\]]*\]){0,2}\{(?:(?:[^{},]*,)*)?(?:\}(?=.*?\{))?){1,}|
#       (?#
#           eighth branch matches most everything else, excluding \volcite,
#           \mcite, \citereset and \citestyle
#           syntax is:
#           \cite[<prenote>][<postnote>]{key}
#       )
#       (?:(?!(?:p|P|f|ft|s|S|t|T|a|A)?volcite|mcite)
#           (?:[A-Z]?[a-z]*c)|C)ite(?!reset\*?|style)([a-zX*]*?)
#           ([.*?]){0,2}(?:\[[^\]]*\]){0,2}\{(?:(?:[^{},]*,)*)?|
#       (?#
#           ninth branch matches apacite commands
#           syntax is:
#           \citeA<prenote>[postnote]{key}
#       )
#       (?:mask)?(?:full|short)cite
#           (?:(?:author|year)(?:NP)?|NP|A)?
#           (?:<[^>]*>)?(?:\[[^\]]*\])?\{(?:(?:[^{},]*,)*)?)$
NEW_STYLE_CITE_REGEX = re.compile(
    r"""(?:
            (?:(?P<prefix1>[^\[\],]*)(?:,[^\[\],]*)*\[\}[^\{]*\{
                \*?etouq(?:kcolb|txet)(?:ngierof|nehpyh|(?<=kcolb)dirbyh))|
            (?:(?P<prefix2>[^\[\],]*)(?:,[^\[\],]*)*\[\*?etouq(?:kcolb|txet))|
            (?:(?P<prefix3>[^{},]*)(?:,[^{},]*)*\{(?:\][^\[]*\[){0,2}\}[^\{]*\{
                \*?etouqc(?:kcolb|txet)(?:ngierof|nehpyh|(?<=kcolb)dirbyh))|
            (?:(?P<prefix4>[^{},]*)(?:,[^{},]*)*\{(?:\][^\[]*\[){0,2}
                \*?etouqc(?:kcolb|txet))|
            (?:(?P<prefix5>[^{},]*)(?:,[^{},]*)*\{(?:\][^\[]*\[)?\}[^\{}]*\{(?:\][^\[]*\[)?
                eticlov(?:p|P|f|ft|s|S|t|T|a|A)?)|
            (?:(?P<prefix6>[^{},]*)(?:,[^{},]*)*\{(?:\][^\[]*\[)?\}[^\{}]*\{(?:\][^\[]*\[)?
                (?:\}[^\{}]*\{(?:\][^\[]*\[)?\}[^\{}]*\{(?:\][^\[]*\[)?)*
                (?:\)[^(]*\(){0,2}
                seticlov(?:p|P|f|ft|s|S|t|T|a|A)?)|
            (?:(?P<prefix7>[^{},]*)(?:,[^{},]*)*\{(?:\][^\[]*\[){0,2}
                (?:\}[^\}]*\{(?:\][^\[]*\[){0,2})*
                (?:[\.\*\?]){0,2}(?:\)[^(]*\(){0,2}
                seti(?:C|c(?!lov)[a-z]*[A-Z]?))|
            (?:(?P<prefix8>[^{},]*)(?:,[^{},]*)*\{(?:\][^\[]*\[){0,2}
                (?:[\.\*\?]){0,2}(?!\*?teser|elyts)(?P<fancy_cite>[a-z\*]*?)
                eti(?:C|c(?!lov|m\\)[a-z]*[A-Z]?))|
            (?:(?P<prefix9>[^{},]*)(?:,[^{},]*)*\{(?:\][^\[]*\[)?
                (?:>[^<]*<)?(?:(?:PN)?(?:raey|rohtua)|PN|A)?etic
                (?:lluf|trohs)?(?:ksam)?)|
            (?:(?P<prefix10>[^{},]*)\{yrtnebib)
        )\\""", re.X)


def match(rex, str):
    m = rex.match(str)
    if m:
        return m.group(0)
    else:
        return None


# find bib files
# recursively search all linked tex files to find all
# included bibliography tags in the document and extract
# the absolute filepaths of the bib files

# known bibliography commands
SINGLE_BIBCOMMANDS = set([
    'addbibresource',
    'addglobalbib',
    'addsectionbib'
])

MULTI_BIBCOMMANDS = set([
    'bibliography',
    'nobibliography'
])


# filter for find_bib_files
def _bibfile_filter(c):
    return (
        c.command in SINGLE_BIBCOMMANDS or
        c.command in MULTI_BIBCOMMANDS or
        c.command == 'newrefsection' or
        (
            c.command == 'begin' and
            c.args == 'refsection'
        )
    )


def find_bib_files(view):
    root = view.file_name()

    # the final list of bib files
    result = set()

    # a list of candidates bib files to check
    resources = []

    resources.extend(['../bibliography.bib'])  # For now...

    resources = [os.path.expanduser(p) for p in resources]

    # extract absolute filepath for each bib file
    rootdir = os.path.dirname(root)
    for res in resources:
        # We join with rootdir, the dir of the master file
        candidate_file = os.path.normpath(os.path.join(rootdir, res))
        print("Trying:", candidate_file)
        # if the file doesn't exist, search the default tex paths
        if not os.path.exists(candidate_file):
            candidate_file = kpsewhich(res, 'mlbib')

        if candidate_file is not None and os.path.exists(candidate_file):
            result.add(str(candidate_file))

    # remove duplicates
    return set(result)


def run_plugin_command(command, *args, expect_result=True, **kwargs):
    '''
    This function is intended to run a command against a user-configurable list
    of bibliography plugins set using the `bibliography` setting.

    Parameters:
        `command`: a string representing the command to invoke, which should
            generally be the name of a function to be called on the plugin
                class.
        `*args`: the args to pass to the function
        `**kwargs`: the keyword args to pass to the function

    Additionally, the following keyword parameters can be specified to control
    how this function works:
        `stop_on_first`: if True (default), no more attempts will be made to
            run the command after the first plugin that returns a non-None
            result
        `expect_result`: if True (default), a BibPluginError will be raised if
            no plugin returns a non-None result

    Example:
        run_plugin_command('get_entries', *bib_files)
        This will attempt to invoke the `get_entries` method of any configured
        plugin, passing in the discovered bib_files, and returning the result.

    The general assumption of this function is that we only care about the
    first valid result returned from a plugin and that plugins that should not
    handle a request will either not implement the method or implement a
    version of the method which raises a NotImplementedError if that plugin
    should not handle the current situation.
    '''

    def _run_command(plugin_name):
        plugin = None
        try:
            plugin = REGISTRY[plugin_name]
        except KeyError:
            pass

        if not plugin:
            error_message = (
                'Could not find bibliography plugin named {0}. '
                'Please ensure your LaTeXTools.sublime-settings is configured'
                'correctly.'.format(plugin_name))
            print(error_message)
            raise BibPluginError(error_message)

        # instantiate plugin
        try:
            plugin = plugin()
        except:     # noqa
            error_message = (
                'Could not instantiate {0}. {0} must have a no-args __init__ '
                'method'.format(type(plugin).__name__,))
            print(error_message)
            raise BibPluginError(error_message)

        try:
            result = getattr(plugin, command)(*args, **kwargs)
        except TypeError as e:
            if "'{0}()'".format(command) in str(e):
                error_message = (
                    '{1} is not properly implemented by {0}.'.format(
                        type(plugin).__name__,
                        command))
                print(error_message)
                raise BibPluginError(error_message)
            else:
                raise e
        except AttributeError as e:
            if "'{0}'".format(command) in str(e):
                error_message = '{0} does not implement `{1}`'.format(
                    type(plugin).__name__, command)
                print(error_message)
                raise BibPluginError(error_message)
            else:
                raise e
        except NotImplementedError:
            return None

        return result

    plugin = get_setting('bibliography', 'traditional')
    if not plugin:
        print('bibliography setting is blank. Loading traditional plugin.')
        plugin = 'traditional'

    result = None
    if not isinstance(plugin, str):
        raise TypeError("Nope!")
    result = _run_command(plugin)

    if expect_result and result is None:
        raise BibPluginError(
            "Could not find a plugin to handle '{0}'. "
            "See the console for more details".format(command))

    return result


def get_cite_completions(view):
    bib_files = find_bib_files(view)
    print("Bib files found: ")
    print(repr(bib_files))

    if not bib_files:
        # sublime.error_message("No bib files found!") # here we can!
        raise NoBibFilesError()

    completions = run_plugin_command('get_entries', *bib_files)

    return completions


# called by LatexFillAllCommand; provides citations for cite commands
class CitePlugin:

    @staticmethod
    def get_auto_completions(view, prefix, line):
        # Reverse, to simulate having the regex
        # match backwards (cool trick jps btw!)
        line = line[::-1]

        # Check the first location looks like a cite_, but backward
        old_style = OLD_STYLE_CITE_REGEX.match(line)

        # Do not match on plain "cite[a-zX*]*?" when autocompleting,
        # in case the user is typing something else
        if old_style and not prefix:
            return []

        try:
            completions = get_cite_completions(view)
        except NoBibFilesError:
            print("No bib files found!")
            sublime.status_message("No bib files found!")
            return []
        except BibParsingError as e:
            message = "Error occurred parsing {0}. {1}.".format(
                e.filename, e.message)
            print(message)
            traceback.print_exc()

            sublime.status_message(message)
            return []

        if prefix:
            lower_prefix = prefix.lower()
            completions = [
                c for c in completions
                if _is_prefix(lower_prefix, c)
            ]

        if len(completions) == 0:
            return []

        cite_autocomplete_format = get_setting(
            'cite_autocomplete_format', '{keyword}: {title}'
        )

        def formatted_entry(entry):
            try:
                return entry['<autocomplete_formatted>']
            except:     # noqa
                return bibformat.format_entry(cite_autocomplete_format, entry)

        completions = [
            (
                formatted_entry(c),
                c['keyword']
            ) for c in completions
        ]

        if old_style:
            return completions, '{'
        else:
            return completions

    @staticmethod
    def get_completions(view, prefix, line):
        try:
            completions = get_cite_completions(view)
        except NoBibFilesError:
            sublime.error_message("No bib files found!")
            return
        except BibParsingError as e:
            traceback.print_exc()
            sublime.error_message(
                "Error occurred parsing {0}. {1}.".format(
                    e.filename, e.message
                )
            )
            return

        if prefix:
            lower_prefix = prefix.lower()
            completions = [
                c for c in completions
                if _is_prefix(lower_prefix, c)
            ]

        completions_length = len(completions)
        if completions_length == 0:
            return
        elif completions_length == 1:
            return [completions[0]['keyword']]

        cite_panel_format = get_setting(
            'cite_panel_format',
            ["{title} ({keyword})", "{author}"]
        )

        def formatted_entry(entry):
            try:
                result = entry["<panel_formatted>"]
                if isinstance(result, tuple):
                    result = list(result)
                return result
            except:     # noqa
                return [
                    bibformat.format_entry(s, entry)
                    for s in cite_panel_format
                ]

        formatted_completions = []
        result_completions = []
        for completion in completions:
            formatted_completions.append(formatted_entry(completion))
            result_completions.append(completion['keyword'])

        return formatted_completions, result_completions

    @staticmethod
    def matches_line(line):
        return bool(
            OLD_STYLE_CITE_REGEX.match(line) or
            NEW_STYLE_CITE_REGEX.match(line)
        )

    @staticmethod
    def matches_fancy_prefix(line):
        return bool(OLD_STYLE_CITE_REGEX.match(line))

    @staticmethod
    def is_enabled():
        return get_setting('cite_auto_trigger', True)


def _is_prefix(lower_prefix, entry):
    try:
        return lower_prefix in entry["<prefix_match>"]
    except:     # noqa
        return lower_prefix in bibformat.create_prefix_match_str(entry)
