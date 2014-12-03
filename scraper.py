
import requests
from urlparse import urlparse
from lxml import html



class ScrapeSite:
    def __init__(self, url):
        self.url = url
        page = requests.get(self.url)
        if page.status_code == 200:
            self.dom = html.fromstring(page.text)


        self.title = None
        self.description = None
        self.keywords = None

        self.hostname = urlparse(self.url).hostname
        self._scrape()

    def _scrape(self):

        self.title = self.get_page_title()

        tag_gen = self.get_meta_tags()

        while not (self.title and self.description and self.keywords):

            e = tag_gen.next()

            if e.get('name') in ["keywords", "news_keywords"] and not self.keywords:
                self.keywords = e.get('content')

            elif (e.get('name') in ['description', 'twitter:description'] or e.get('property') in ['og:description']) \
                    and not self.description:
                self.description = e.get('content')

            elif (e.get('name') in ['title', 'twitter:title'] or e.get('property') in ['og:title']) \
                    and not self.description:
                self.description = e.get('content')

    def get_meta_tags(self):
        res = []
        for e in self.dom.xpath('.//meta'):
            yield e.attrib

    def get_page_title(self):
        return self.dom.find(".//title").text

    def get_site_dict(self):
        res = {"url": self.url, "hostname" : self.hostname,
               "title": self.title, "description": self.description,
               "keywords": self.keywords}


if __name__ == "__main__":
    url = "http://gawker.com/boy-found-behind-fake-wall-set-escape-in-motion-with-a-1665938754"
    g  = ScrapeSite(url)