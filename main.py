import play_scraper
import requests
import webapp2
import wsgiref.handlers

from bs4 import BeautifulSoup
from google.appengine.api import urlfetch
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from requests_toolbelt.adapters import appengine
from google.appengine.api import taskqueue

appengine.monkeypatch()

PLAY_STORE_URL = "https://play.google.com/store/apps/top"
q = taskqueue.Queue('sync-apps-queue')


class Application(db.Model):
    """
    Model for representing an Application
    """
    app_id = db.StringProperty(indexed=True, required=True)
    updated_on = db.DateTimeProperty(auto_now_add=True)
    category = db.StringProperty()
    video = db.StringProperty()
    title = db.StringProperty()
    icon = db.StringProperty()
    developer = db.StringProperty()
    screenshots = db.StringListProperty()
    score = db.StringProperty()
    installs = db.StringProperty()
    description = db.TextProperty()


class MainPageClass(webapp2.RequestHandler):
    def get(self):
        # In case of re-scrape button pressed on the main page, same api would be called
        # with re_scrape flag as True in the request
        query_params = self.request.GET.items()
        re_scrape = False
        for param in query_params:
            if param[0] == 're_scrape' and param[1] == 'True':
                re_scrape = True
        if re_scrape:
            q.add(taskqueue.Task(payload='', method='PULL', tag='sync_apps'))
            self.redirect('/')

        query = db.Query(Application)
        query_data = query.order('-updated_on')
        category_wise_data = {}
        for app_item in query_data:
            if not category_wise_data.get(app_item.category):
                category_wise_data[app_item.category] = []
            if len(category_wise_data[app_item.category]) < 3:
                category_wise_data[app_item.category].append(app_item)
        self.response.write(template.render('main_page.html', {'data_dict': category_wise_data}))


class RescrapeDataClass(webapp2.RequestHandler):
    def get(self):
        """
        API to re-scrape data from play store and store it in datastore db.
        """
        tasks = q.lease_tasks_by_tag(3600, 100, 'sync_apps')
        # Re scrape data from play-store for top charts
        rescrape_data()
        # Delete the tasks which are leased from the pull queue
        q.delete_tasks(tasks)


def rescrape_data():
    """
    Re scrapes data from play store to datastore db
    """
    category_to_app_ids_mapping = {}
    # Make play store api call
    r = urlfetch.fetch(PLAY_STORE_URL)
    # self.response.write(r.content)
    soup = BeautifulSoup(r.content, 'html.parser')
    all_categories = soup.find_all('div', class_="Ktdaqe")
    for category in all_categories:
        top_apps_in_category = category.find_all('div', class_='vU6FJ p63iDd')
        top_apps_in_category = top_apps_in_category[0:3][::-1]
        name = category.find('div', class_='xwY9Zc').text
        if not category_to_app_ids_mapping.get(name):
            category_to_app_ids_mapping[name] = []
        for item in top_apps_in_category:
            app_link = item.a['href']
            app_id = app_link.split('?')[1].split('id=')[1]
            category_to_app_ids_mapping[name].append(app_id)

    for key, value in category_to_app_ids_mapping.items():
        for app_id in value:
            app_details = play_scraper.details(app_id)
            query_result = Application.all().filter('app_id =', app_id)
            app_obj = None
            for obj in query_result:
                app_obj = obj
            if not app_obj:
                app_obj = Application(app_id=app_id)
            app_obj.category = key
            app_obj.developer = app_details['developer']
            app_obj.title = app_details['title']
            app_obj.icon = app_details['icon']
            app_obj.screenshots = app_details['screenshots']
            if app_obj.screenshots and len(app_obj.screenshots) > 4:
                if not app_obj.video and len(app_obj.screenshots) > 5:
                    app_obj.screenshots = app_obj.screenshots[0:5]
                else:
                    app_obj.screenshots = app_obj.screenshots[0:4]
            app_obj.video = app_details['video']
            app_obj.score = app_details['score']
            app_obj.installs = app_details['installs']
            app_obj.description = app_details['description']
            app_obj.put()


class DetailsPageClass(webapp2.RequestHandler):
    def get(self):
        query_params = self.request.GET.items()
        app_id = None
        for param in query_params:
            if param[0] == 'app_id':
                app_id = param[1]
                break
        if not app_id:
            self.response.write('No app found')
            return
        app_from_data_store = Application.all().filter('app_id =', app_id)
        app_obj = None
        for obj in app_from_data_store:
            app_obj = obj
        if not app_obj:
            self.response.write('No App found, please select a valid app_id')
        else:
            self.response.write(template.render('details_page.html', {'obj': app_obj}))


app = webapp2.WSGIApplication([
        ('/', MainPageClass),
        ('/appdetails', DetailsPageClass),
        ('/rescrape_data', RescrapeDataClass)
    ], debug=True)


def main():
    # from paste import httpserver
    # httpserver.serve(app, host='127.0.0.1', port='8080')
    wsgiref.handlers.CGIHandler().run(app)


if __name__ == '__main__':
    main()
