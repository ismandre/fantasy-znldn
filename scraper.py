"""
scrapers/hns_semafor.py

Dependencies:
  pip install requests beautifulsoup4 python-dateutil

Usage pattern:
  from scrapers.hns_semafor import CompetitionScraper
  scraper = CompetitionScraper("https://semafor.hns.family/natjecanja/101384257/1-znl-2526/")
  data = scraper.scrape_all()
"""

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

USER_AGENT = "FantasyScraper/1.0 (+https://yourdomain.example)"

class CompetitionScraper:
    def __init__(self, competition_url, session=None):
        self.base_url = competition_url
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def fetch(self, url):
        r = self.session.get(url)
        r.raise_for_status()
        return r.text

    def soup(self, url):
        html = self.fetch(url)
        return BeautifulSoup(html, "html.parser")

    def scrape_all(self):
        soup = self.soup(self.base_url)
        comp = self.parse_competition_meta(soup)
        teams = self.parse_teams(soup)
        fixtures = self.parse_fixtures(soup)
        standings = self.parse_standings(soup)
        player_stats = self.parse_player_stats(soup)
        return {
            "competition": comp,
            "teams": teams,
            "fixtures": fixtures,
            "standings": standings,
            "player_stats": player_stats,
        }

    def parse_competition_meta(self, soup):
        # Example: page shows a H1 or heading with competition name and season
        title = soup.find("h1")
        if title:
            name = title.get_text(strip=True)
        else:
            name = soup.title.string if soup.title else self.base_url
        # Try to find season label text nearby
        season_text = None
        season_elem = soup.find(text=re.compile(r"\d{4}/\d{4}"))
        if season_elem:
            season_text = season_elem.strip()
        return {"name": name, "season_label": season_text, "url": self.base_url}

    def parse_teams(self, soup):
        """
        Find team links/names. On the sample page each team appears as an <a> to a team page.
        We'll collect href, name and image if present.
        """
        teams = {}
        # find anchors that look like team links - heuristic: href contains '/klub' or link text looks like uppercase name or ends with team
        anchors = soup.find_all("a", href=True)
        for a in anchors:
            href = a['href']
            text = a.get_text(" ", strip=True)
            if not text:
                continue
            # heuristics: team links often point to klub pages or include "NK", "HNK", "ONK", "BŠK", etc.
            if re.search(r"/klub|^NK |^HNK |^ONK |^BŠK |^GNK |^NK ", text, re.I) or re.search(r"/klub", href):
                full_href = urljoin(self.base_url, href)
                # get image if inside link
                img = a.find("img")
                img_src = urljoin(self.base_url, img["src"]) if img and img.get("src") else None
                hns_id_match = re.search(r"/klub/(\d+)", href)
                hns_id = hns_id_match.group(1) if hns_id_match else href
                teams[text] = {"name": text, "url": full_href, "crest": img_src, "hns_id": hns_id}
        # fallback: sometimes teams are listed as list items with class 'team' - try to find unique team names in page
        if not teams:
            candidate_texts = set()
            for tag in soup.select("div, li, span"):
                txt = tag.get_text(" ", strip=True)
                if re.match(r"^(NK|HNK|ONK|BŠK|GNK)\b", txt):
                    candidate_texts.add(txt)
            for t in candidate_texts:
                teams[t] = {"name": t, "url": None, "crest": None, "hns_id": None}
        return list(teams.values())

    def parse_fixtures(self, soup):
        """
        Parse fixtures: date headings followed by match rows.
        Returns list of match dicts:
        {'date': datetime, 'home': 'Team A', 'away': 'Team B', 'home_goals': int or None, 'away_goals': int or None, 'venue': '...', 'match_url': '...'}
        """
        fixtures = []
        # The page uses "Raspored, rezultati, strijelci" and then rounds like "* 1. kolo" and list of matches.
        # Find blocks that look like fixtures: date (like 28.09.2025.) and subsequent links with scores.
        # We'll search for patterns of date text followed by siblings containing anchors and score text.
        # Find any element that contains a date pattern
        date_nodes = soup.find_all(text=re.compile(r"\d{2}\.\d{2}\.\d{4}\.?"))
        seen = set()
        for node in date_nodes:
            parent = node.parent
            # Walk siblings to find match entries within the same parent or next ul
            block = parent
            # collect nearby anchors that likely represent teams and score spans
            # We search following elements in parent's next siblings up to N nodes
            current = block
            for sib in list(current.next_siblings)[:40]:
                text = getattr(sib, "get_text", lambda **k: "")(strip=True)
                # if it contains a team anchor + score pattern, try to extract
                anchors = sib.find_all("a") if hasattr(sib, "find_all") else []
                if len(anchors) >= 2 and re.search(r"\d+\s*:\s*\d+", sib.get_text(" ", strip=True)):
                    # extract teams and score
                    a_texts = [a.get_text(" ", strip=True) for a in anchors[:2]]
                    score_match = re.search(r"(\d+)\s*:\s*(\d+)", sib.get_text(" ", strip=True))
                    home_goals = int(score_match.group(1)) if score_match else None
                    away_goals = int(score_match.group(2)) if score_match else None
                    # look for venue in same block
                    venue = None
                    v = sib.find_next(string=re.compile(r"[A-Za-z0-9ČĆŽŠĐčćžšđ ,\-]+"))
                    # attempt to parse date + time from original date node text
                    dt = self._parse_datetime_from_context(node)
                    fixtures.append({
                        "date": dt,
                        "home": a_texts[0],
                        "away": a_texts[1],
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "venue": venue,
                        "match_url": None
                    })
                # stop if a new date or round appears
                if re.search(r"\d{2}\.\d{2}\.\d{4}\.", getattr(sib, "get_text", lambda **k: "")()):
                    break
        # As a fallback: search for any score patterns and pick surrounding anchors as teams
        if not fixtures:
            all_nodes = soup.find_all(string=re.compile(r"\d+\s*:\s*\d+"))
            for node in all_nodes:
                parent = node.parent
                anchors = parent.find_all("a")
                if len(anchors) >= 2:
                    a_texts = [a.get_text(strip=True) for a in anchors[:2]]
                    score_match = re.search(r"(\d+)\s*:\s*(\d+)", node)
                    fixtures.append({
                        "date": None,
                        "home": a_texts[0],
                        "away": a_texts[1],
                        "home_goals": int(score_match.group(1)),
                        "away_goals": int(score_match.group(2)),
                        "venue": None,
                        "match_url": None
                    })
        return fixtures

    def _parse_datetime_from_context(self, text_node):
        txt = text_node.strip()
        # The page uses format "28.09.2025. 16:00" or "28.09.2025."
        try:
            # replace dots to conform to parseable format
            # ensure trailing time exists
            dt_txt = re.sub(r"\.", "", txt).strip()
            # common pattern dd.mm.YYYY HH:MM
            # replace dot-space with space
            dt_txt = txt.replace(".", "").strip()
            # Try parsing
            dt = dateparser.parse(dt_txt, dayfirst=True, fuzzy=True)
            return dt
        except Exception:
            return None

    def parse_standings(self, soup):
        """
        Parse standings table if present. Returns list of dicts per row.
        """
        tables = soup.find_all("table")
        standings = []
        for table in tables:
            # Heuristic: table headers with 'Poz.', 'Klub', 'B', 'W', 'D', 'L', 'B.', 'Gol razlika', or 'Bodovi'
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if any(h in " ".join(headers) for h in ("poz", "klub", "bod")):
                # parse rows
                for tr in table.select("tbody tr"):
                    tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                    if not tds:
                        continue
                    # attempt to map columns: [pos, team, played, wins, draws, losses, gf-ga, gd, pts]
                    try:
                        pos = int(tds[0])
                        team_name = None
                        # team might be second column, maybe contains anchor
                        team_cell = tr.find_all("td")[1]
                        team_name = team_cell.get_text(" ", strip=True)
                        played = int(tds[2]) if len(tds) > 2 and tds[2].isdigit() else 0
                        wins = int(tds[3]) if len(tds) > 3 and tds[3].isdigit() else 0
                        draws = int(tds[4]) if len(tds) > 4 and tds[4].isdigit() else 0
                        losses = int(tds[5]) if len(tds) > 5 and tds[5].isdigit() else 0
                        gf = int(tds[6]) if len(tds) > 6 and tds[6].isdigit() else 0
                        ga = int(tds[7]) if len(tds) > 7 and tds[7].isdigit() else 0
                        pts = int(tds[-1]) if tds[-1].isdigit() else 0
                        standings.append({
                            "position": pos,
                            "team": team_name,
                            "played": played,
                            "wins": wins,
                            "draws": draws,
                            "losses": losses,
                            "goals_for": gf,
                            "goals_against": ga,
                            "points": pts,
                        })
                    except Exception:
                        continue
        return standings

    def parse_player_stats(self, soup):
        """
        Parse player lists and stats sections like 'Strijelci' (scorers), 'Kartoni' (cards), 'Nastupi / minute'
        We'll return dicts keyed by player name with stats we can find.
        """
        stats = {}
        # Sections appear with headings 'Strijelci', 'Kartoni', 'Nastupi / minute'
        # Find headings with these texts
        for heading_text in ("Strijelci", "Kartoni", "Nastupi / minute", "Strijelci, kartoni"):
            heading = soup.find(lambda tag: tag.name in ("h2", "h3", "h4", "strong") and heading_text in tag.get_text())
            if not heading:
                # try any element containing the text
                heading = soup.find(text=re.compile(heading_text))
                if heading:
                    heading = heading.parent
            if not heading:
                continue
            # players are typically in the following list elements
            for sib in heading.find_next_siblings():
                # break if we encounter a new major section
                if sib.name and sib.name.startswith("h"):
                    break
                # look for player blocks (anchored names and numeric columns)
                # many player entries are like: <div> <img> <h3><a>Player Name</a></h3> <div>Igrač</div> [goals] [minutes] ...
                player_anchors = sib.select("a")
                for a in player_anchors:
                    name = a.get_text(strip=True)
                    if not name:
                        continue
                    # parent block text
                    block_text = sib.get_text(" ", strip=True)
                    # extract numbers in the block (goals, minutes etc) - heuristics
                    numbers = re.findall(r"\b\d+\b", block_text)
                    # assign heuristically: first number might be goals or appearances
                    goals = None
                    minutes = None
                    if heading_text == "Strijelci":
                        goals = int(numbers[0]) if numbers else 0
                    elif heading_text == "Nastupi / minute":
                        if len(numbers) >= 2:
                            appearances = int(numbers[0])
                            minutes = int(numbers[1])
                        elif len(numbers) == 1:
                            appearances = int(numbers[0])
                            minutes = None
                    elif heading_text == "Kartoni":
                        # maybe yellow/red counts in block
                        yellow = int(numbers[0]) if numbers else 0
                        red = int(numbers[1]) if len(numbers) > 1 else 0
                        stats.setdefault(name, {}).update({"yellow_cards": yellow, "red_cards": red})
                    stats.setdefault(name, {}).update({
                        "full_name": name,
                        "goals": goals if goals is not None else stats.get(name, {}).get("goals"),
                        "minutes": minutes if minutes is not None else stats.get(name, {}).get("minutes")
                    })
                # if the sibling is a big list group and we've collected some players, stop further siblings
                if stats:
                    # continue scanning - but may want to limit
                    pass
        return stats

