#!/usr/bin/env python3
import sys
import os
import re
from mappings import userMapping
import xml.etree.ElementTree as ET
from markdownify import MarkdownConverter
from bs4 import BeautifulSoup
# For user names
import ldap

ldapserver = 'ldap://ldap.keg.cse.unsw.edu.au'
base = 'ou=Accounts,dc=keg,dc=cse,dc=unsw,dc=edu,dc=au'
searchAttributes=['cn', 'uid']

ld = ldap.initialize(ldapserver)
ld.protocol_version = ldap.VERSION3
searchFilter=[]
for x in userMapping:
    searchFilter.append('(uid=' + userMapping[x] + ')')
searchFilter = '(|' + ''.join(searchFilter) + ')'

# Build dictionary of uid->name from our ldap database
LDAPusers = ld.search(base, ldap.SCOPE_SUBTREE, searchFilter, searchAttributes)
LDAPuserName = {}
while True:
    result_type, result_data = ld.result(LDAPusers, 0)
    if result_data == []:
        break
    if result_type == ldap.RES_SEARCH_ENTRY:
        results = result_data[0][1]
        if 'uid' in results:
            uid = results['uid'][0].decode('utf-8')
            name = results['cn'][0].decode('utf-8')
            LDAPuserName[uid] = name

class ConfluenceConverter(MarkdownConverter):
    """
    Pass through some macros
    """
    def convert_panel(self, el, text, convert_as_inline):
        title =  el.get('title')
        if title:
            title = 'title="%s"' % title
        else:
            title = ''
        tt = el.get('type')
        if tt:
            tt = 'type="%s" ' % tt
        else:
            tt = ''
        return "<panel %s %s>%s</panel>" % (title, tt, text)

def md(html, **options):
    return ConfluenceConverter(**options).convert(html)


# WHAT THIS DOES
# reads from 'entities.xml', finds pages, finds their content,
# converts that to markdown, and dumps markdown files in the 
# following directory structure:
#   Pages / Status / Parent_Page / Child_Page / title=version.md
# 
# Also, attachments are found (from the export) in:

#  attachments / PageID / AttachmentID / version (files)
# This script currently renames the highest version of each
# attachment, to the appropriate filename
# (when that attachment is referenced).
# 



# There will be a page object for every version of a page
# in its history. Here we keep track of the highest version
# (i.e. most current) page.
hiversions={}
users={}
attachments = {}
attachmentIndex = {}
pageNames = {}
outDated = []

emoticons_symbols = {
    "smile" : ":-)",
    "information": "ⓘ",
    "red-star": '<span style="color:red">٭</span>',
    "yellow-star": '<span style="color:yellow">٭</span>',
    "minus": "---",
    "tick": "✓",
    "cross" : "❌",
    "cheeky" : ":‑p",
    "laugh": ":-D",
    "wink" : ";‑)",
    "sad" : ":‑(",
    "question" : ":?:",
    "tongue": ":-P",
    "big grin": "=)",
    "slightly_smiling_face" : ":-|",
    "thumbs-up": "👍",
    "thumbs-down": "👎",
    "warning" : "⚠",
    
}

def localname(csiro_id):
    if csiro_id in userMapping:
        return userMapping[csiro_id]
    return csiro_id

# Eventually add in an ldap lookup to convert to local user 
class ConfluenceUser:
    def __init__(self, id, email, first, last, userid):
        self.id = id
        self.email = email
        self.name = first + ' ' + last
        login = localname(userid)
        if login in LDAPuserName:
            self.name = LDAPuserName[login]
        self.userid = login or first + '_' + last
        users[id] = self

    def __str__(self):
        if (self.email):
            return "%s: %s %s <%s>" % (self.userid, self.first, self.last, self.email)
        else:
            return "%s" % (self.userid)

class Page:
    def __init__(self, id, parent, version, bodyid, title, status, attaches):
        self.id = id
        self.title = title
        self.parent = parent
        self.version = int(version)
        self.bodyId = bodyid
        self.status = status
        self.attaches = attaches
        pages[id] = self
        self.history = []
        if title:
            self.filename = page_name_to_filename(title)
        else:
            self.filename = '__unknown__'
        self.fullpath = self.filename
        self.tag = self.filename
        self.namespace = ':oldwiki'
        self.children = []
        if title not in hiversions or hiversions[title] < self.version:
            hiversions[title] = self.version
            pageNames[title] = self

    def title_or_id(self):
        return self.title or '[ID:%s]' % (self.id)

    def is_latest(self):
       return self.title not in hiversions or hiversions[self.title] == self.version

class Attachment:
    def __init__(self, id, title):
        self.id = id
        self.title = title
        self.page = None        
        self.filename = ''
        attachments[id] = self
        attachmentIndex[title] = self

    def __str__(self):
        return 'Attachment %s: "%s"' % (self.id, self.title)

def get_user(userkey):
    if (userkey in users):
        return users[userkey]
    return None

def find_attachment_in_page(link_name, page):
    for a in page.attaches:
        if (a.title == link_name):
            return a.id
    return '0'

def sanitise_link_name(linkname):
    return linkname.replace(":", "")

def rename_attachment_file(attach_id, safe_filename, page):
    dir = 'attachments/%s/%s' % (page.id, attach_id)
    # get all files
    try: files = [f for f in os.listdir(dir)]
    except FileNotFoundError: return
    # get all files that can be parsed as an int
    max_filenum = 0
    for f in files:
        # if the file already exists, skip this process
        if (f == safe_filename): return
        try:
            f_num = int(f)
            if f_num > max_filenum:
                max_filenum = f_num
        except: pass
    orig_filepath = os.path.join(dir, str(max_filenum))
    os.makedirs(os.path.dirname(safe_filename), exist_ok=True)
    try:
        os.link(orig_filepath, safe_filename)
    except:
        pass

# TODO: the files are actually just called 1/2/3 etc (no extension)
# these names seem to be version names, so I think we should rename/copy the highest numbered file
# to the appropriate filename, maybe even as part of this function
def make_attachment_link(link_name, soup, page):
    attach_id = find_attachment_in_page(link_name, page)
    if attach_id == '0':
        print("Can't find attachment %s" % link_name)
        return link_name
    attachment = attachments[attach_id]
    if attachment.filename == '':
        attachment.filename = page.filename.replace('pages/current/', 'media/') +\
        '/' + page_name_to_filename(attachment.title)
    rename_attachment_file(attach_id, attachment.filename, page)
    tag = "{{%s|%s}}" % (attachment.filename.replace('media/', '').replace('/', ':'), link_name)
    return tag

def make_attachment_image(link_name, soup, page):
    attach_id = find_attachment_in_page(link_name, page)
    if attach_id == '0':
        print("Can't find image %s" % link_name)
        return 'IMAGE:  ' + link_name
    attachment = attachments[attach_id]
    rename_attachment_file(attach_id, attachment.filename, page)
    fn = attachment.filename
    if fn.startswith('media/'):
        fn = fn[5:]
    tag = "{{%s|%s}}" % (fn.replace('/', ':'), link_name)
    return tag

def make_internal_link(page_name, soup):
    tag = '[[%s|%s]]' % (page_name_to_filename(page_name).replace('/', ':').replace('pages:', ':'), page_name)
    return tag

def make_internal_link_p(page, soup):
    tag = '[[%s|%s]]' % (page.tag, page.title)
    return tag

def make_toc(page: Page, soup):
    hh = soup.new_tag("h2")
    hh.string = "Pages below this page:"
    soup.append(hh)
    toc = soup.new_tag("ul")
    for child in page.children:
        li = soup.new_tag("li")
        li.append(make_internal_link_p(child, soup))
        toc.append(li)
    soup.append(toc)
    return soup

def make_toc_page(page: Page):
    soup = BeautifulSoup('');
    title = soup.new_tag("h1")
    title.string = page.title
    soup.insert(0, title)
    make_toc(page, soup)
    return str(soup)

def make_attachment_index(page: Page, unref_attachments):
    soup = BeautifulSoup('')
    if len(unref_attachments) == 0:
        return soup
    title = soup.new_tag('h2')
    title.string = "Attachments"
    soup.append(title)
    idx = soup.new_tag('ul')
    for x in unref_attachments:
        li = soup.new_tag('li')
        li.append(make_attachment_link(x.title, soup, page))
        idx.append(li)
    soup.append(idx)
    return soup

# DokuWiki always inserts a table of contents, so just delete the macro
def toc_macro(soup, page):
    return ''

# Assumes the subpages plugin is installed
def subpages_macro(soup, page):
    return '{{pglist> files dirs}}'

# Just elide the macro, replace with contents
def null_macro(soup, page):
    return soup.find('ac:rich-text-body') or ''
    
def attachments_macro(soup, page):
    return make_attachment_index(page, page.attaches)

def code_macro(soup, page):
    lang = soup.find_all(attrs = {"ac:name", "language"})
    body = soup.find('ac:plain-text-body')
    if body is None:
        print('Page %s: macro has no plain-text-body' % page.title)
        print('"""' + '\n'.join(soup.contents) + '"""')
        return soup
    content = body.contents
    soup = BeautifulSoup('')
    pre = soup.new_tag('pre')
    code = soup.new_tag('code')
    if lang:
        code['language'] = lang.string
    code.contents = content
    pre.append(code)
    return pre

def details_macro(soup, page):
    body = soup.find('ac:rich-text-body')
    return body

def gallery_macro(soup, page):
    return 'Insert Gallery Here'

# The status macro encloses its arg in a coloured box.
def status_macro(soup, page):
    colour = soup.find_all(attrs={'ac:name', 'colour'})
    if colour:
        colourStyle = 'padding:2px; background-color:' + colour.string + ';'
        print('Colour styling %s' % colourStyle)
        colour.replace_with('')
    else:
        colourStyle = ''
    content = soup.get_text()
    if content is None:
        return ''
    soup = BeautifulSoup('')
    span = soup.new_tag('span')
    span.attrs['style'] = '%s font-size:130%%; border=2px;' % colourStyle
    span.string = content
    soup.append(span)
    return soup
    
def box_macro(soup, page, boxtype, title = None):
    content = soup.find('ac:rich-text-body').contents
    soup = BeautifulSoup('')
    panel = soup.new_tag('panel')
    panel['type'] = boxtype
    if title:
        panel['title'] = title
    panel.contents = content
    soup.append(panel)
    return soup

def info_macro(soup, page):
    return box_macro(soup, page, 'info');

def tip_macro(soup, page):
    return box_macro(soup, page, 'default', title = 'tip');

def warning_macro(soup, page):
    return box_macro(soup, page, 'warning');

def danger_macro(soup, page):
    return box_macro(soup, page, 'danger');

def note_macro(soup, page):
    return box_macro(soup, page, 'default', title='Note');

def panel_macro(soup, page):
    title = soup.find('ac:parameter', attrs={'ac:name', 'title'})
    body = soup.find('ac:rich-text-body').contents
    soup = BeautifulSoup('')
    panel = soup.new_tag('panel')
    if title:
        panel['title'] = title.string
    panel.contents = body
    soup.append(panel)
    return soup

def column_macro(soup, page):
    width = soup.find_all(attrs = {'ac:name': 'width'})
    body = soup.find('ac:rich-text-body')
    soup = BeautifulSoup('');
    col = soup.new_tag('col')
    col.contents = body.contents
    if width:
        col['lg'] = str(int(width[0].string.strip('%')) * 12 /100)
    soup.append(col)
    return soup

def section_macro(soup, page):
    body = soup.find('ac:rich-text-body')
    soup = BeautifulSoup('')
    row = soup.new_tag('row')
    row.contents = body.contents
    soup.append(row)
    return soup

handleMacro = {
    'code' : code_macro,
    'details' : details_macro,
    'noformat': code_macro,
    'gallery': gallery_macro,
    'toc' : toc_macro,
    'attachments': attachments_macro,
    'expand': null_macro,
    # consider adding the columns plugin to DokuWiki and generating the
    # appropriate markup
    'anchor' : null_macro,
    'section': section_macro,
    'column': column_macro,
    'panel' : panel_macro,
    'children': subpages_macro,
    'status':status_macro,
    'info': info_macro,
    'tip': tip_macro,
    'note': note_macro,
    'warning': warning_macro,
    'danger': danger_macro
    }

# run this before markdownify.
# 'confluence' is the PageContent for a page
# this is for processing some special things before html2markdown
# by converting some special confluence macros into normal HTML
def convert(confluence, page):
    if confluence == '':
        return make_toc_page(page)
    soup = BeautifulSoup(confluence, "html.parser")
    title = soup.new_tag("h1")
    title.string = page.title
    soup.insert(0, title)

    if len(page.children):
        toc = BeautifulSoup("")
        toc = make_toc(page, toc)
        soup.insert(1, toc)

    # Users
    allusers = soup.find_all('ri:user')
    for ll in allusers:
        try:
            user = get_user(ll['ri:userkey'])
            if user is None:
                username = 'UnknownUser'
        except KeyError:
            try:
                user = None
                username = ll['ri:username']
            except KeyError:
                print (ll)
                raise Exception("malformed user")
       
        pp=ll.parent
        if pp.name == 'ac:link':
            if user:
                pp.replace_with('[[user>%s|%s]]' % (user.userid, user.name))
            else:
                pp.replace_with('@' + username)
        else:
            raise Exception("User found that is not a link")

    # Attachments
    unhandled = set(page.attaches)
    allattachments = soup.find_all('ri:attachment')
    for ll in allattachments:
        link_filename = ll['ri:filename']
        pp=ll.parent
        if link_filename in attachmentIndex:
            id = attachmentIndex[link_filename]
            if id in unhandled:
                unhandled.remove(id)
        parent_id = ll.find('ri:content-entity')
        if parent_id:
            if parent_id in pages:
                apage  = pages[parent_id['ri:content-id']]
            else:
                # reference is to a page outside the dump
                apage = page 
        else:
            apage = page
        if pp.name == 'ac:link':
            pp.replace_with(make_attachment_link(link_filename, soup, apage))
        elif pp.name == 'ac:image':
            pp.replace_with(make_attachment_image(link_filename, soup, apage))
        elif hasattr(pp.parent, 'ac:name') and \
            pp.parent['ac:name'] == 'view-file' or pp.parent['ac:name'] == 'viewpdf':
            # other types of file embeds, which we will just make into attachment links
            pp.replace_with(make_attachment_link(link_filename, soup, apage))
        else:
            print ("unrecognised attachment:")
            print(pp)
            print (pp.parent)
            raise Exception("Attachment found that is neither link nor image")

    soup.append(make_attachment_index(page, unhandled))

    # Internal Links
    allintlinks = soup.find_all('ri:page')
    if (len(allintlinks)):
        for link in allintlinks:
            pp = link.parent
            if (pp.name == 'ac:link'):
                linkedPageTitle = link['ri:content-title']
                if linkedPageTitle in pageNames:
                    pp.replace_with(make_internal_link_p(pageNames[linkedPageTitle], soup))
                else:
                    print('%s not in pageNames' % linkedPageTitle)
                    pp.replace_with(make_internal_link(linkedPageTitle, soup))
            else:
                raise Exception("Page found that is not a link")

    # Task lists
    tlists = soup.find_all('ac:task-list')
    if (len(tlists)):
        for tl in tlists:
            for task in tl.find_all('ac:task'):
                #TODO: due dates
                taskid = task.find("ac:task-id")
                body = task.find("ac:task-body")
                status = task.find("ac:task-status") or None
                task.name = "li"
                taskid.decompose()
                completed = False
                if (status and status.getText() == "complete"):
                    completed = True
                status.decompose()
                if (completed):
                    body.insert(0, "[COMPLETE] ")
            tl.name = "ul"

    #emoticons 1
    emoticons = soup.find_all(attrs = {"class": "emoticon"})
    if len(emoticons):
        for em in emoticons:
            ti = em.attrs["title"].strip('():')
            if ti in emoticons_symbols:
                em.replace_with(emoticons_symbols[ti])
            else:
                print("Unknown emoticon :%s:" % ti)
                em.replace_with(':%s:' % ti)

    emoticons = soup.find_all('ac:emoticon')
    if len(emoticons):
        for em in emoticons:
            ti = em['ac:name']
            if ti in emoticons_symbols:
                em.replace_with(emoticons_symbols[ti])
            else:
                print("Unknown emoticon :%s:" % ti)
                em.replace_with(':%s:' % ti)


    # macros blocks
    macros = soup.find_all('ac:structured-macro')
    if len(macros):
        for cc in macros:
            name = cc['ac:name']
            if name in handleMacro:
                print('macro ' + name)
                cc.replace_with(handleMacro[name](cc, page))
            else:
                print("Unhandled macro %s in page '%s'" % (
                    name, page.title))
                x = re.sub(r'<', r'&#60;', str(cc))
                x = re.sub(r'>', r'&#62;', x)
                cc.wrap(soup.new_tag('pre'))
                cc.replace_with(x)
                
            
    return str(soup)

# given a Page, build a filepath for that page,
# with intelligent folder structure
def build_path(page: Page):
    status = page.status
    pathname = [page.filename]
    while page.parent is not None:
        page = pages[page.parent]
        pathname.insert(0, page.filename)
    pathname.insert(0, status)
    pathname.insert(0, 'Pages')
    pathname = '/'.join(pathname)
    return pathname.lower()

# ------------ load entities.xml ------------

print('Loading "entities.xml" from current directory... ', end='')

tree=ET.parse('entities.xml')
root=tree.getroot()

print('Done.')

if root.tag != 'hibernate-generic':
    print('not a Confluence export')
    sys.exit(1)

print ('Confluence export recognised')


# ------------ find users ------------
print ('Finding users...')
users={}
for obj in root.findall('object[@class="ConfluenceUserImpl"]'):
    id = obj.find('id').text
    userid = ''
    email = ''
    try:
        userid = obj.find('property[@name="name"]').text or None
        email = obj.find('property[@name="email"]').text or ''
    except:
        pass

    # if we have an email, extract first and last names from the email addr
    if len(email) > 1:
        xxx = email.split('@')
        xxx = xxx[0].split('.')
        first = xxx[0]
        if len(xxx) > 1:
            last = xxx[1]
        else:
            last = first
    else:
        first = ''
        last = ''

    # create a ConfluenceUser (constructor will add itself to 'users')
    ConfluenceUser(id, email, first, last, userid)

emailcount = sum(1 for x in users if users[x].email)
print ("Found %s users. %s with email+name, %s without." % (len(users), emailcount, len(users)-emailcount))



# ------------ prepare attachments ------------
attachments = {}

def addAttachment(obj):
    id = obj.find('id').text
    title = obj.find('property[@name="title"]').text
    Attachment(id, title)


print('Processing attachments... ', end='')
for obj in root.findall('object[@class="Attachment"]'):
    addAttachment(obj)
print('Done.')


# ------------ process pages ------------
pages = {}

# build a Page object from an XML object for that page
def addPage(obj, is_blog=False):
    id = obj.find('id').text
    title = obj.find('property[@name="title"]').text
    # try to find the parent id
    try:
        parent = obj.find('property[@name="parent"]')
        parent = parent.find('id').text
    except:
        if is_blog:
            parent = "0"
        else:
            parent = None
    version = obj.find('property[@name="version"]').text or '0'
    body = obj.find('collection/element[@class="BodyContent"]')
    if body is None:
        bodyId = '0'
    else:
        bodyId = body.find('id').text
    status = obj.find('property[@name="contentStatus"]').text

    # create a list of associated attachments
    attaches = []
    attachcoll = obj.find('collection[@name="attachments"]')
    if attachcoll:
        for att in attachcoll.findall('element[@class="Attachment"]'):
            attachid = att.find('id').text
            attaches.append(attachments[attachid])
    
    # create a Page (will add itself to 'pages')
    pp = Page(id, parent, version, bodyId, title, status, attaches)
    oldVersions = obj.find('collection[@name="historicalVersions"]')
    if oldVersions is None:
        return
    for v in oldVersions.findall('element[@class="Page"]'):
        oldId = v.find('id').text
        pp.history.append(oldId)
        outDated.append(oldId)

def page_name_to_filename(pagename):
    s = pagename.replace('/', '-').replace(' ', '_')
    s = re.sub(r'[^-A-Za-z0-9_.]+', '', s).lower()
    s = re.sub(r'_+', '_', s)
    return s


report_empty_pages = False

# find all pages
print('Grabbing raw pages... ', end='')
for obj in root.findall('object[@class="Page"]'):
    addPage(obj)
print('Done.')
if report_empty_pages:
    pages_without_content = [pages[x].title_or_id() for x in pages if pages[x].bodyId=='0']
    if (len(pages_without_content)):
        print('The following pages have no content: ', pages_without_content)

# find all blog posts
# first, create the 'root' blog post
pages["0"] = Page("0", None, "0", "0", "Blog Posts", "current", [])
print('Grabbing raw blog posts... ', end='')
for obj in root.findall('object[@class="BlogPost"]'):
    addPage(obj, True)
print('Done.')
if report_empty_pages:
    blogs_without_content = [pages[x].title_or_id() for x in pages if pages[x].bodyId=='0']
    if (len(blogs_without_content)):
        print('The following pages have no content: ', blogs_without_content)


# index all the BodyContent objects
PageContent = {}
for obj in root.findall('object[@class="BodyContent"]'):
    id = obj.find('id').text
    content = obj.find('property[@name="body"]').text or ''
    PageContent[id] = content

# Dump pages and content (only first 10 for now)
count = 0
totalcount = len(pages)
percent = int(totalcount/100)

# Make a pass to find full 'pathnames' for files, and to create child lists
print('Creating page and attachment hierarchy ...')
for x, p in list(pageNames.items()):
    p.pathname = build_path(p)
    p.tag = p.pathname.replace('/', ':').replace('pages:current', ':oldwiki')
    #print(p.tag, p.pathname, p.title)
    if p.parent in pages and p.status == "current":
        pages[p.parent].children.append(p)
    for attachment in p.attaches:
        attachment.page = p
        attachment.filename = p.pathname.replace('pages/current', 'media/oldwiki') + \
      '/' +  page_name_to_filename(attachment.title)
    if p.id in outDated:
        del(pageNames[x])


print ('Processing and exporting into markdown...')
for x in pageNames:
    p = pageNames[x]
    count+=1
    if (count % percent == 0):
        print ('%s pages exported (%s%%)' % (count, round(count*100/totalcount)))
    
    # skip if no content
    if p.bodyId == '0': continue
    # skip if not latest version
    if not p.is_latest(): continue
    # get the path and content
    pathname = p.pathname
    filename = pathname + '.txt'
    converted_confl = convert(PageContent[p.bodyId], p)
    # print ('\n' + converted_confl + '\n')
    markdown = md(converted_confl)
    # print ('\n--------------------\n\n\n' + markdown + '\n')

    # markdown = "meow"
    # print('%s --> %s' % (p.title_or_id(), filename))

    # write the markdown to file
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    f = open(filename, 'w', encoding="utf-8")
    f.write(markdown)
    f.close()

    f = open("most_recent_page.md", 'w', encoding="utf-8")
    f.write(markdown)
    f.close()

    # input('\n\nPress Enter to do the next one...\n\n\n')

print('Done.')
