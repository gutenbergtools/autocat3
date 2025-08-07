# code moved from AdvSearchPage so it could be used in Basesearcher
import cherrypy
from sqlalchemy import or_, and_, select

from libgutenberg.Models import (
    Alias, Attribute, Author, Book, BookAuthor, Category, File, Lang, Locc, Subject)


_LANGOPTIONS = ''
_LANGLOTS = ''
_LANGLESS = ''
_LANGS = {}

# can't make a session until CherryPy is finished starting
def makelangs():
    global _LANGOPTIONS, _LANGLOTS, _LANGLESS, _LANGS
    if _LANGOPTIONS or _LANGLOTS or _LANGLESS:
        return _LANGS
    session = cherrypy.engine.pool.Session()
    for lang in session.execute(select(Lang.id, Lang.language).order_by(Lang.language)).all():
        _LANGS[lang[0]] = lang[1]
        langnum = session.query(Book).filter(Book.langs.any(id=lang[0])).count()
        _LANGOPTIONS += f'<option value="{lang[0]}">{lang[1]}</option>'
        lang_link  = f'/ebooks/search/?query=l.{lang[0]}'
        if langnum > 50:
            _LANGLOTS += f'<a href="{lang_link}" title="{lang[1]} ({langnum})">{lang[1]}</a> | '
        elif langnum > 0:
            _LANGLESS += f'<a href="{lang_link}" title="{lang[1]} ({langnum})">{lang[1]}</a> | '
    return _LANGS

def langoptions():
    ''' option list for langs dropdown '''
    global _LANGOPTIONS
    if _LANGOPTIONS:
        return _LANGOPTIONS
    else:
        makelangs()
        return _LANGOPTIONS

def langlots():
    ''' list of links for langs with more than 50 books '''
    global _LANGLOTS
    if not _LANGLOTS:
        makelangs()
    return _LANGLOTS[0:-2]  # cut trailing |

def langless():
    ''' list of links for langs with up to 50 books '''
    global _LANGLESS
    if not _LANGLESS:
        makelangs()
    return _LANGLESS[0:-2]  # cut trailing |

def langname(code):
    return makelangs().get(code.lower(), 'Not a valid language')

_cats = {}

def catname(catpk):
    """ cache of category names"""
    if not _cats:
        session = cherrypy.engine.pool.Session()
        for cat in session.query(Category).all():
            _cats[cat.pk] = cat.category
    try:
        catpk = int(catpk)
    except ValueError:
        return 'Not a valid Category'
    return _cats.get(catpk, 'Not a valid Category')

_locs = {}

def locname(id):
    """ cache of classification names"""
    if not _locs:
        session = cherrypy.engine.pool.Session()
        for loc in session.query(Locc).all():
            _locs[loc.id] = loc.locc
    return _locs.get(id.upper(), 'Not a valid Classification')
