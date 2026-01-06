#!/usr/bin/env python3
"""
Script to convert the contents of a Mastodon export archive to Jekyll posts.

It may work for any ActivityPub-compatible platform, but I have only tried it
with Mastodon.

Jim Pingle <jim@pingle.org>
"""

import json, re, sys, os, shutil, html, yaml, string
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

"""Customize the following variables as needed"""

archive_filename = './outbox.json'
"""File extracted from archive containing post data"""

posts_dir        = './_posts'
"""Directory where the script will write post files"""

attachment_dir   = './assets/images'
"""Directory where the script will copy attachment files (images, video)"""

my_actor         = 'https://mastodon.example.com/users/myname'
"""The URL for the ActivityPub user/actor to ensure it only processes your posts"""

local_timezone   = 'America/Indiana/Indianapolis'
"""Local timezone, posts are typically in GMT"""

set_published    = False
"""Default status of generated posts. False is safer so they can be previewed."""

post_layout      = "single"
"""Post layout may vary by theme, e.g. for Minimal Mistakes it is 'single'."""

max_title_words  = 15
"""The maximum number of words to use when generating post titles/slugs."""

keep_tag_links   = False
"""When forming post text, remove hashtag links and text. This is good for posts
with hashtags at the end, but can break posts with inline hashtags."""

wanted_tags = [
	'#sometopic',
	'#cats'
]
"""List of tags to restrict which posts are included. Leave blank to process all posts."""

debug = False
"""Set to True and the script will print debugging output as it works"""

""" *** *** Do not change things below here *** *** """

def read_archive(archive_filename):
	'''
	Read archive file and parse JSON into a dict.
	:archive_filename: Path and file of archive (e.g. 'output.json')
	:returns: Dict containing contents of the archive.
	'''
	with open(archive_filename) as f:
		archive = json.load(f)

	return archive

def get_post_tags(post, lowercase=True, removeoctothorpe=False):
	'''
	Collect a list of all hashtags in the post.
	:post: Post instance from archive
	:lowercase: Whether or not to make returned tags lowercase.
	:removeoctothorpe: Remove the leading # from tags.
	:returns: List containing tags from the post.
	'''
	posttags = []

	# If there is no post['object']['tag'] or it's not a list, bail
	if 'tag' not in post['object'] or \
		not isinstance(post['object']['tag'], list):
		return []

	# Only collect Hashtag type entries
	for tag in post['object']['tag']:
		if tag['type'] == 'Hashtag':
			tagname = tag['name']
			if lowercase:
				tagname = tagname.lower()
			if removeoctothorpe:
				tagname = tagname.lstrip('#')
			# Add to list of tags
			posttags.append(tagname)

	return posttags

def make_post_title(post):
	'''
	Uses the first few words of the post as the title. Stops early when it
	reaches	the end of a sentence or a newline.

	:post: Post instance from archive
	:returns: Plain text string suitable for use as the title of a post.
	'''

	title = ""

	# Add blank line between paragraphs otherwise they run together when stripping HTML
	withnewlines = post['object']['content'].replace("</p><p>", "</p>\n\n<p>")
	# Make copy of body text with HTML stripped
	plaintext = html.unescape(re.sub(r"<.*?>", "", withnewlines))
	# Split into separate words, using at most max_title_words words.
	firstwords = plaintext.split()[:max_title_words]

	# Start assembling the title
	titlewords = []
	for word in firstwords:
		# Clean up some characters that don't work in titles
		word = word.replace(':', '')
		word = word.replace('"', '')
		word = word.replace("'", '')
		# Add word to title
		titlewords.append(word)

		# Stop early if we reach the end of a sentence or a newline.
		if word.endswith('.') or \
			word.endswith('\n'):
			break

	# Re-join words into a title and remove trailing punctuation.
	return ' '.join(titlewords).rstrip(string.punctuation)

def make_post_slug(post):
	'''
	Creates a "slug" from the post title which can be used as part of the
	filename/URL.

	:post: Post instance from archive
	:returns: Post slug with words separated by hyphens.
	'''

	# Force to lowercase
	title = make_post_title(post).lower()
	# Remove all punctuation
	title = title.translate(str.maketrans('', '', string.punctuation))
	# Remove double spaces, Separate with hyphens
	return re.sub(r"\s", "-", title.replace('  ', ' '))

def make_post_filename(post):
	'''
	Creates a filename for the post using the post date and slug, e.g.
	``YYYY-MM-DD-<title-slug>.markdown``

	:post: Post instance from archive
	:returns: Path and filename for the post.
	'''

	slug = make_post_slug(post)
	# Convert date to local timezone and output in YYYY-MM-DD format.
	postdate = datetime.fromisoformat(post['published']).astimezone(ZoneInfo(local_timezone)).strftime("%Y-%m-%d")
	# Craft filename using the post directory, date, slug, and extension.
	return posts_dir + "/" + postdate + "-" + slug + ".markdown"

def make_front_matter(post):
	'''
	Creates front matter for the post.

	:post: Post instance from archive
	:returns: Front matter in YAML format.
	'''

	# I know this is probably less elegant than using the yaml library.
	fm =  "---\n"
	# Post layout, which may vary by theme
	fm += "layout: " + post_layout + "\n"

	# Published status
	fm += "published: " + str(set_published).lower() + "\n"

	# Post title
	fm += "title: " + make_post_title(post) + "\n"

	# Post date in the preferred YAML format
	postdate = datetime.fromisoformat(post['published']).astimezone(ZoneInfo(local_timezone))
	fm += "date: " + postdate.strftime("%Y-%m-%d %H:%M:%S %z") + "\n"

	# Make a dummy excerpt or it will take the whole first paragraph
	fm += 'excerpt: "..."\n'

	# Generate category list from tags
	posttags = get_post_tags(post, False, True)
	fm += "categories:\n" + yaml.dump(posttags, default_flow_style=False)

	# Now a tag list in the shorter format.
	fm += "tags: " + yaml.dump(posttags, default_flow_style=True)

	fm += "---\n"
	return fm

def process_attachments(post):
	'''
	Processes attachments from ActivityPub format to Jekyll tags and copies
	the attached files as needed.

	:post: Post instance from archive
	:returns: Text with tags to add the attachments to the post.
	  Files are copied into attachment_dir
	'''

	att_txt = ""

	# If there are no attachments on the post, return an empty string.
	if 'attachment' not in post['object'] or \
		not isinstance(post['object']['attachment'], list):
		return ""

	# Process each attachment in the post
	for att in post['object']['attachment']:
		entry_text = ""

		# These files should also be in the archive after it was
		# extracted. However, the URL starts with /, so prefix with . to
		# ensure it uses the correct path.
		archive_media_file = "." + att['url']

		# Target filename for the attachment
		post_media_file = attachment_dir + '/' + os.path.basename(archive_media_file)
		if not os.path.isfile(archive_media_file):
			print("Attachment file missing: ", archive_media_file)
			continue

		# Check if it's image or video
		if att['mediaType'].startswith('image/'):
			# If it's an image, use the figure helper
			entry_text += '\n{% include figure popup=true image_path="'
			entry_text += post_media_file + '"'
			# Add alt text if present
			if (att['name']):
				entry_text += ' alt="' + html.escape(att['name'].replace('\n', ' ')) + '"'

			entry_text += ' %}\n'
		elif att['mediaType'].startswith('video/'):
			# If it's a video, use the <video> tag
			entry_text += '\n<video src="'
			entry_text += post_media_file.lstrip('.') + '" controls="controls"'
			# Add alt text if present
			if (att['name']):
				entry_text += ' alt="' + html.escape(att['name'].replace('\n', ' ')) + '"'

			# Add width if present
			if (att['width']):
				entry_text += ' style="max-width: ' + str(att['width']) + 'px;"'

			entry_text += '></video>\n'

		att_txt += entry_text

		# Create the attachment directory if it does not exist.
		if not os.path.exists(attachment_dir):
			os.makedirs(attachment_dir)

		# copy file from archive_media_file into attachment_dir
		shutil.copy2(archive_media_file, post_media_file)

	return att_txt

def make_post_text(archive, post):
	'''
	Create text from a given post, its attachments, and all of its replies.
	Acts recursively to build an entire thread, in the order given in the
	reply metadata.
	:archive: Archive dict containing all data (including posts)
	:post: The specific post to start with.
	:returns: String containing the post text for the entire thread with
	  attachments.
	'''

	# If the post is empty, bail.
	if not post:
		return ""

	# Start with the text of this post.
	bodytext = post['object']['content'] + "\n"

	# Remove hashtag links that we don't need or want.
	bs = BeautifulSoup(bodytext, 'html.parser')
	if not keep_tag_links:
		for tag in bs.find_all("a", class_="mention hashtag"):
			tag.decompose()
	bodytext = bs.prettify()

	# Process attachments, if any are present.
	att_txt = process_attachments(post)
	if (att_txt):
		bodytext += "\n" + att_txt

	# Find replies, but be extra sure the entire structure is present and
	# in the expected format.
	# Not exactly elegant, but easier to follow than some shorter methods.
	if 'replies' in post['object'] and \
		isinstance(post['object']['replies'], dict) and \
		'first' in post['object']['replies'] and \
		isinstance(post['object']['replies']['first'], dict) and \
		'items' in post['object']['replies']['first'] and \
		isinstance(post['object']['replies']['first']['items'], list) and \
		post['object']['replies']['first']['items']:
		if debug: print("Seeking replies: ", len(post['object']['replies']['first']['items']))
		for reply in post['object']['replies']['first']['items']:
			# Locate the reply post by its ID
			replypost = find_post_by_id(archive, reply)
			# If we found the reply post in the archive, process it
			if replypost:
				if debug: print("Processing reply!")
				bodytext += "\n" + make_post_text(archive, replypost)

	return bodytext

def find_post_by_id(archive, postid):
	'''
	Iterate archive looking for post with a specific id

	:archive: Archive dict containing all data (including posts)
	:postid: The post ID value to look for.
	:returns: Post object for the given ID if found, or an empty dict
	  otherwise.
	'''
	# Iterate every post in the archive
	for apost in archive['orderedItems']:
		# If the object isn't usable, skip it.
		if not isinstance(apost, dict) or \
			'object' not in apost or \
			not isinstance(apost['object'], dict) or \
			'id' not in apost['object']:
			continue

		# Make sure this entry is from the proper actor
		if apost['actor'] != my_actor or \
			apost['object']['attributedTo'] != my_actor:
			if debug: print("Skipping reply: Wrong actor.")
			continue

		# If we found the post we were after, return it
		if apost['object']['id'] == postid:
			if debug: print("Found reply ", postid)
			return apost

	# Return an empty dict if we couldn't locate the post.
	return {}

def main():
	# List of posts that were processed, mainly to track the count.
	target_posts = []
	try:
		archive = read_archive(archive_filename)
		for apost in archive['orderedItems']:
			post_text = ""
			# If apost and/or apost['object'] are not usable, skip entry
			if not isinstance(apost, dict) or \
				'object' not in apost or \
				not isinstance(apost['object'], dict):
				if debug: print("Skipping post: Object not usable.")
				continue

			# Make sure this entry is from the proper actor
			if apost['actor'] != my_actor or \
				apost['object']['attributedTo'] != my_actor:
				if debug: print("Skipping post: Wrong actor.")
				continue

			# Make sure this is the first post of a thread
			if 'inReplyTo' in apost['object'] and \
				apost['object']['inReplyTo']:
				if debug: print("Skipping post: Is a reply.")
				continue

			# Collect a list of all hashtags in the post.
			posttags = get_post_tags(apost)

			# If we want tags and there are no tags, skip.
			if wanted_tags and not posttags:
				if debug: print("Skipping post: No tags.")
				continue

			# Check for overlap between tag list and wanted tags, skip to next post if no match
			if wanted_tags and \
				not bool(set(wanted_tags) & set(posttags)):
				if debug: print("Skipping post: No wanted tags.")
				continue

			# Check if this is a boost
			title = make_post_title(apost)
			if title.startswith("RE: "):
				if debug: print("Skipping post: Boost.")
				continue

			if debug: print("Found a post!\n")

			# Make front matter:
			post_text += make_front_matter(apost)

			# Add post text
			post_text += "\n" + make_post_text(archive, apost)

			# Add link to original Mastodon post
			post_text += "\n[Imported from Mastodon](" + apost['object']['url'] + ")\n\n"

			if debug: print(post_text)

			filename = make_post_filename(apost)

			# Create the posts directory if it does not exist.
			if not os.path.exists(posts_dir):
				os.makedirs(posts_dir)

			# Only write the file if it does not exist, for safety.
			try:
				with open(filename, "x", encoding="utf-8") as f:
					f.write(post_text)
				# Track how many posts we have processed.
				target_posts.append(apost['object']['id'])
			except FileExistsError:
				print(filename, "already exists, not overwriting.")

		print("Total Posts Generated: ", len(target_posts))

	except ValueError as err:
		return str(err)

if __name__ == "__main__":
	sys.exit(main())
