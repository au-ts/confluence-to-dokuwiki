#!/usr/bin/env python3
import sys
import os
import shutil
import xml.etree.ElementTree as ET
from markdownify import markdownify
from bs4 import BeautifulSoup
# also required: LXML (pip install lxml)



# WHAT THIS DOES
# reads from 'entities.xml', finds pages, finds their content,
# converts that to markdown, and dumps markdown files in the 
# following directory structure:
#   Pages / Status / Parent_Page / Child_Page / title=version.md
# 
# Also, attachments are found (from the export) in:
#  attachments / PageID / AttachmentID / version (files)
# This script currently renames the highest version of each
# attachment, in the existing folder, to the appropriate filename
# (when that attachment is referenced).
# 



# There will be a page object for every version of a page
# in its history. Here we keep track of the highest version
# (i.e. most current) page.
hiversions={}

users={}

attachments = {}


# Eventually add in an ldap lookup to convert to local user 
class ConfluenceUser:
    def __init__(self, id, email, first, last, userid):
        self.id = id
        self.email = email
        self.first = first
        self.last = last 
        self.userid = userid or first + '_' + last
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
        if title:
            self.filename = title.replace(' ', '_').replace('&', 'and').replace('/','_')
        else:
            self.filename = '__unknown__'
        if title not in hiversions or hiversions[title] < self.version:
            hiversions[title] = self.version
    
    def title_or_id(self):
        return self.title or '[ID:%s]' % (self.id)

    def is_latest(self):
       return self.title not in hiversions or hiversions[self.title] == self.version

class Attachment:
    def __init__(self, id, title):
        self.id = id
        self.title = title
        attachments[id] = self

    def __str__(self):
        return 'Attachment %s: "%s"' % (self.id, self.title)

def get_userid(userkey):
    if (userkey in users):
        return users[userkey].userid
    return 'UNKNOWN_USER'

def find_attachment_in_page(link_name, page):
    for a in page.attaches:
        if (a.title == link_name):
            return a.id
    return '0'

def sanitise_link_name(linkname):
    return linkname.replace(":", "")

def rename_attachment_file(filename, safe_filename, page):
    attach_id = find_attachment_in_page(filename, page)
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
    new_filepath  = os.path.join(dir, safe_filename)
    shutil.copy(orig_filepath, new_filepath)

# TODO: the files are actually just called 1/2/3 etc (no extension)
# these names seem to be version names, so I think we should rename/copy the highest numbered file
# to the appropriate filename, maybe even as part of this function
def make_attachment_link(link_name, soup, page):
    safe_link_name = sanitise_link_name(link_name)
    rename_attachment_file(link_name, safe_link_name, page)
    attach_id = find_attachment_in_page(link_name, page)
    full_url = 'attachments/%s/%s/%s' % (page.id, attach_id, link_name)
    tag = soup.new_tag("a", href=full_url)
    tag.string = link_name
    return tag

def make_attachment_image(link_name, soup, page):
    safe_link_name = sanitise_link_name(link_name)
    rename_attachment_file(link_name, safe_link_name, page)
    attach_id = find_attachment_in_page(link_name, page)
    full_url = 'attachments/%s/%s/%s' % (page.id, attach_id, link_name)
    tag = soup.new_tag("img", src=full_url)
    return tag

def make_internal_link(page_name, soup):
    tag = soup.new_tag("a", href=page_name_to_filename(page_name))
    tag.string = page_name
    return tag


# run this before markdownify.
# 'confluence' is the PageContent for a page
# this is for processing some special things before html2markdown
# by converting some special confluence macros into normal HTML
def convert(confluence, page):
    soup = BeautifulSoup(confluence, features="lxml")
    title = soup.new_tag("h1")
    title.string = page.title
    soup.insert(0, title)

    # Users
    allusers = soup.find_all('ri:user')
    for ll in allusers:
        try:
            user = get_userid(ll['ri:userkey'])
        except KeyError:
            try:
                user = ll['ri:username']
            except KeyError:
                print (ll)
                raise Exception("malformed user")
        pp=ll.parent
        if pp.name == 'ac:link':
            pp.replace_with('@' + user)
        else:
            raise Exception("User found that is not a link")

    # Attachments
    allattachments = soup.find_all('ri:attachment')
    for ll in allattachments:
        link_filename = ll['ri:filename']
        pp=ll.parent
        if pp.name == 'ac:link':
            pp.replace_with(make_attachment_link(link_filename, soup, page))
        elif pp.name == 'ac:image':
            pp.replace_with(make_attachment_image(link_filename, soup, page))
        elif hasattr(pp.parent, 'ac:name') and pp.parent['ac:name'] == 'view-file' or pp.parent['ac:name'] == 'viewpdf':
            # other types of file embeds, which we will just make into attachment links
            pp.replace_with(make_attachment_link(link_filename, soup, page))
        else:
            print ("unrecognised attachment:")
            print(pp)
            print (pp.parent)
            raise Exception("Attachment found that is neither link nor image")

    # Internal Links
    allintlinks = soup.find_all('ri:page')
    if (len(allintlinks)):
        for link in allintlinks:
            pp = link.parent
            if (pp.name == 'ac:link'):
                linkedPageTitle = link['ri:content-title']
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
    return str(soup)

# given a Page, build a filepath for that page,
# with intelligent folder structure
def build_path(page: Page):
    status = page.status
    pathname = [page.filename]
    while page.parent is not None:
        page = pages[page.parent]
        pathname.insert(0, page_name_to_filename(page.filename))
    pathname.insert(0, status)
    pathname.insert(0, 'Pages')
    pathname = '/'.join(pathname)
    return pathname









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
    Page(id, parent, version, bodyId, title, status, attaches)


def page_name_to_filename(pagename):
    return pagename.replace("'", "").replace('"', '').replace("?","").replace(":","")


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

print ('Processing and exporting into markdown...')
# Dump pages and content (only first 10 for now)
count = 0
totalcount = len(pages)
percent = int(totalcount/100)
for x in pages:
    p = pages[x]
    count+=1
    if (count % percent == 0):
        print ('%s pages exported (%s%%)' % (count, round(count*100/totalcount)))
    
    # skip if no content
    if p.bodyId == '0': continue
    # skip if not latest version
    if not p.is_latest(): continue
    # get the path and content
    pathname = build_path(p)
    filename = page_name_to_filename(pathname) + '=' + str(p.version) + '.md'
    converted_confl = convert(PageContent[p.bodyId], p)
    # print ('\n' + converted_confl + '\n')
    markdown = markdownify(converted_confl)
    # print ('\n--------------------\n\n\n' + markdown + '\n')

    # markdown = "meow"
    # print('%s --> %s' % (p.title_or_id(), filename))

    # write the markdown to file
    os.makedirs(os.path.dirname(build_path(p)), exist_ok=True)

    f = open(filename, 'w', encoding="utf-8")
    f.write(markdown)
    f.close()

    f = open("most_recent_page.md", 'w', encoding="utf-8")
    f.write(markdown)
    f.close()

    # input('\n\nPress Enter to do the next one...\n\n\n')

print('Done.')