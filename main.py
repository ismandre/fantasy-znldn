# main.py
from scraper import CompetitionScraper

def print_header(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

def main():

    print_header("Scraping League Info")

    scraper = CompetitionScraper("https://semafor.hns.family/natjecanja/101384257/1-znl-2526/")
    data = scraper.scrape_all()
    print_header("FINISHED")
    print("Scraper test completed successfully!")
    from pprint import pprint
    pprint(data)

if __name__ == "__main__":
    main()
