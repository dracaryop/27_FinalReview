
import urllib.request
from bs4 import BeautifulSoup
import sys
import re
import urllib.parse
import hashlib
import string
import codecs
from nltk.stem import PorterStemmer


class WebCrawler:
    def __init__(self, seed_url):
        self.seed_url = seed_url
        self.domain_url = "/".join(self.seed_url.split("/")[:3])
        self.robots_txt = None
        self.stop_words_file = None
        self.page_limit = None
        self.stop_words = []  # list of words to be ignored when processing documents
        self.url_frontier = []  # list of urls not yet visited
        self.visited_urls = {}  # URL : (Title, DocumentID) (hash of content of a visited URL)
        self.outgoing_urls = []
        self.broken_urls = []
        self.graphic_urls = []
        self.all_terms = []  # set of all stemmed terms in all documents
        self.frequency_matrix = []  # Term doc frequency matrix (row=term, col=doc)
        self.num_pages_crawled = 0  # number of valid pages visited
        self.num_pages_indexed = 0  # number of pages whose words have been stored

        """
        note: the attributes below only contain information from those documents whose 
              words were saved (.txt, .htm, .html, .php)
        """
        self.duplicate_urls = {}  # DocumentID : [URLs that produce that ID]
        self.doc_urls = {}  # DocumentID: first URL that produces that ID
        self.doc_titles = {}  # DocumentID : title
        self.doc_words = {}  # DocumentID : [words]

    # print the report produced from crawling a site
    def __str__(self):
        report = "\nPages crawled: " + str(self.num_pages_crawled) \
                 + "\nPages indexed: " + str(self.num_pages_indexed) \
                 + "\nVisited URLs: " + str(len(self.visited_urls)) \
                 + "\n\nOutgoing URLs: " + "\n  +  " + "\n  +  ".join(self.outgoing_urls) \
                 + "\n\nBroken URLs: " + "\n  +  " + "\n  +  ".join(self.broken_urls) \
                 + "\n\nGraphic URLs: " + "\n  +  " + "\n  +  ".join(self.graphic_urls) \
                 + "\n\nDuplicate URLs:\n"

        # print duplicate urls
        for key in range(len(self.duplicate_urls.keys())):
            report += "\t +  Doc" + str(key + 1) + ":\n"
            for val in list(self.duplicate_urls.values())[key]:
                report += "\t\t  +  " + val + "\n"

        return report

    '''
    Returns a dictionary of allowed and disallowed urls
    Adapted from https://stackoverflow.com/a/43086135/8853372
    '''
    def get_robots_txt(self):
        # open seed url
        result = urllib.request.urlopen(self.seed_url + "/robots.txt").read()
        result_data_set = {"Disallowed": [], "Allowed": []}

        # for reach line in the file
        for line in result.decode("utf-8").split('\n'):
            if line.startswith("Allow"):
                result_data_set["Allowed"].append(
                    self.seed_url + line.split(": ")[1].split('\r')[0]
                )  # to neglect the comments or other junk info
            elif line.startswith("Disallow"):  # this is for disallowed url
                result_data_set["Disallowed"].append(
                    self.seed_url + line.split(": ")[1].split('\r')[0]
                )  # to neglect the comments or other junk info

        return result_data_set

    def set_page_limit(self, limit):
        self.page_limit = int(limit)

    # sets the stop words list given a file with stop words separated by line
    def set_stop_words(self, filepath):
        try:
            with open(filepath, "r") as stop_words_file:
                stop_words = stop_words_file.readlines()

            self.stop_words = [x.strip() for x in stop_words]
            self.stop_words_file = filepath

        except IOError as e:
            print("Error opening" + filepath + " error({0}): {1}".format(e.errno, e.strerror))
        except ValueError:
            print("Error opening" + filepath + ": Data is not correctly formatted. See README.")
        except:
            print("Error opening" + filepath + "Unexpected error:", sys.exc_info()[0])
            raise

    '''
    returns whether or not a url is valid
    source: https://stackoverflow.com/a/7160778/8853372
    '''
    def url_is_valid(self, url_string):
        pattern = re.compile(
            r'^(?:http|ftp)s?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$',
            re.IGNORECASE)

        return bool(pattern.match(url_string))

    '''
    returns whether or not a given word is valid
    A word is a string of non-space characters, beginning with an alphabetic character. 
    It may contain special characters, but the last character of a word is either alphabetic or numeric.
    '''
    def word_is_valid(self, word):
        pattern = re.compile(r'^[a-zA-z](\S*)[a-zA-z0-9]$')

        return bool(pattern.match(word))

    # returns whether or not the url is within the scope of the seed url
    def url_is_within_scope(self, url_string):
        return self.seed_url in url_string

    '''
    produces a list of duplicate documents
    populates self.duplicate_urls with DocumentID : [URLs that produce that ID]
    '''
    def produce_duplicates(self):
        duplicates = {}

        # populate duplicates with DocumentID : [URLs]
        for url, (_, docID) in self.visited_urls.items():
            duplicates[docID] = [url] if duplicates.get(docID) is None else duplicates[docID] + [url]

        # set duplicate_urls to those instances that have only one URL
        self.duplicate_urls = {docID: urls for docID, urls in duplicates.items() if len(urls) > 1}

    # crawls a site and returns a dictionary of information found
    def crawl(self):
        # dictionary containing information about the site
        self.robots_txt = self.get_robots_txt()

        print("robots.txt: " + " ".join("{}{}".format(key, [
            v.replace(self.domain_url, "") for v in val]) for key, val in self.robots_txt.items()) + "\n")

        self.url_frontier.append(self.seed_url + "/")

        '''
        pop from the URL frontier while the queue is not empty
        links in queue are valid, full urls
        '''
        while self.url_frontier and (self.page_limit is None or self.num_pages_indexed < self.page_limit):
            # current_page refers to the url of the current page being processed
            current_page = self.url_frontier.pop(0)  # select the next url

            # calculate present working directory
            pwd = "/".join(current_page.split("/")[:-1]) + "/"

            if pwd not in self.robots_txt["Disallowed"]:
                try:
                    # hit the current page
                    handle = urllib.request.urlopen(current_page)

                # basic HTTP error e.g. 404, 501, etc
                except urllib.error.HTTPError as e:
                    if current_page not in self.broken_urls and current_page is not None:
                            self.broken_urls.append(current_page)
                else:
                    current_content = str(handle.read())

                    # convert content to BeautifulSoup for easy html parsing
                    soup = BeautifulSoup(current_content, "lxml")

                    # grab the title of the page, store file name if title isn't available (e.g. PDF file)
                    current_title = str(soup.title.string) if soup.title is not None else current_page.replace(pwd, '')

                    # hash the content of the page to produce a unique DocumentID
                    current_doc_id = hashlib.sha256(current_content.encode("utf-8")).hexdigest()

                    # mark that the page has been visited by adding to visited_url
                    self.visited_urls[current_page] = (current_title, current_doc_id)
                    self.num_pages_crawled += 1

                    print(str(self.num_pages_crawled) + ". " + "Visiting: " +
                          current_page.replace(self.domain_url, "") + " (" + current_title + ")")

                    # if the page is an html document, we need to parse it for links
                    if any((current_page.lower().endswith(ext) for ext in ["/", ".html", ".htm", ".php", ".txt"])):

                        # remove contents of title tag
                        [s.extract() for s in soup('title')]

                        # format the content of the page
                        formatted_content = codecs.escape_decode(bytes(soup.get_text().lower(), "utf-8"))[0].decode("utf-8", errors='replace')

                        # store only the words of the file
                        content_words = list(re.sub('[' + string.punctuation + ']', '', formatted_content).split())

                        # remove the 'b' character that's prepended when converting
                        content_words[0] = content_words[0][1:]

                        # keep track of only those words that are valid and not in the stop word collection
                        self.doc_words[current_doc_id] = [w for w in content_words
                                                      if w not in self.stop_words and self.word_is_valid(w)]

                        # store the title
                        self.doc_titles[current_doc_id] = current_title

                        # store the url if it hasn't been stored already (to avoid duplicates)
                        if current_doc_id not in self.doc_urls:
                            self.doc_urls[current_doc_id] = current_page

                        self.num_pages_indexed += 1

                        # go through each link in the page
                        for link in soup.find_all('a'):
                            # current_url refers to the current link within the current page being processed
                            current_url = link.get('href')

                            # expand the url to include the domain
                            if current_url is not None and pwd not in current_url:
                                # only works if the resulting link is valid
                                current_url = urllib.parse.urljoin(pwd, current_url)

                            # the link should be visited
                            if current_url is not None and self.url_is_valid(current_url):

                                # the link is within scope and hasn't been added to the queue
                                if self.url_is_within_scope(current_url) and current_url not in self.url_frontier:

                                    # ensure the hasn't been visited before adding it to the queue
                                    if current_url not in self.visited_urls.keys():
                                        self.url_frontier.append(current_url)

                                elif not self.url_is_within_scope(current_url) and current_url not in self.outgoing_urls:
                                    self.outgoing_urls.append(current_url)

                            # the link is broken
                            elif current_url not in self.broken_urls and current_url is not None:
                                self.broken_urls.append(current_url)

                    # file is a graphic, mark it as such
                    elif any(current_page.lower().endswith(ext) for ext in [".gif", ".png", ".jpeg", ".jpg"]):
                        self.graphic_urls.append(current_page)

            else:
                print("Not allowed: " + current_page.replace(self.domain_url, ""))

    '''
    convert word listings into term-document frequency matrix
    populates frequency_matrix and all_terms
    '''
    def build_frequency_matrix(self):
        if self.doc_words is not None:
            # use porter stemmer for comparing words
            stemmer = PorterStemmer()

            # grab the unique, stemmed terms from all the documents
            self.all_terms = list(set([stemmer.stem(word) for word_list in self.doc_words.values() for word in word_list]))
            self.all_terms.sort()

            # initialize frequency matrix for one row per term
            self.frequency_matrix = [[] for i in self.all_terms]

            # add term frequencies to the matrix
            for term in range(len(self.all_terms)):
                # append the number of times the stemmed words match
                frequency_count = []

                for word_list in self.doc_words.values():
                    stemmed_word_list = [stemmer.stem(word) for word in word_list]
                    frequency_count.append(stemmed_word_list.count(self.all_terms[term]))

                self.frequency_matrix[term] = frequency_count

    # returns the contents of self.frequency_matrix
    def print_frequency_matrix(self):
        output_string = ","

        if self.doc_words is not None:
            # create file heading
            for i in range(len(self.doc_words.keys())):
                output_string += "Doc" + str(i) + ","
            output_string += "\n"

            # add matrix row to output string
            for i in range(len(self.frequency_matrix)):
                output_string += self.all_terms[i] + "," + ",".join([str(i) for i in self.frequency_matrix[i]]) + "\n"

        return output_string

    # returns a zip object containing n elements: (term, total term frequency, doc frequency)
    def n_most_common(self, n):
        term_totals = []
        sorted_terms = self.all_terms
        doc_freqs = []

        # calculate the total frequencies and doc frequencies of each term
        for row in self.frequency_matrix:
            term_totals.append(sum(row))
            doc_freqs.append(sum([1 for x in row if x > 0]))

        # sort terms and doc frequencies based off total frequencies
        sorted_terms = [x for _, x in sorted(zip(term_totals, sorted_terms))]
        doc_freqs = [x for _, x in sorted(zip(term_totals, doc_freqs))]
        term_totals.sort()

        # return n most common
        return zip(reversed(sorted_terms[-n:]), reversed(term_totals[-n:]), reversed(doc_freqs[-n:]))