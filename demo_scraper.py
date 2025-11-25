import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup, Tag


@dataclass
class GoalEvent:
    team: str
    player: str
    minute: int


@dataclass
class PlayerEvent:
    minute: int
    raw: str  # raw text like "60'" – type (card/sub) may need extra logic


@dataclass
class PlayerInfo:
    name: str
    shirt_number: Optional[int]
    position: Optional[str]
    is_captain: bool
    is_starting: bool
    events: List[PlayerEvent]


@dataclass
class MatchData:
    url: str
    competition: Optional[str]
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    venue: Optional[str]
    city: Optional[str]
    date_time: Optional[datetime]
    goals: List[GoalEvent]
    lineups: Dict[str, List[PlayerInfo]]  # team -> players list


GOAL_MINUTE_RE = re.compile(r"(\d+)'")
DATETIME_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4}\.)\s+(\d{2}:\d{2})")


def _get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _parse_header_info(soup: BeautifulSoup):
    """Parse competition, teams, scores from the big H1."""
    h1 = soup.find("h1")
    if not h1:
        raise RuntimeError("Could not find match title <h1>")

    title = " ".join(h1.get_text(" ", strip=True).split())
    # Expected shape:
    # "NK Hajduk 1932 - NK Croatia Gabrili 4:3, 1. ŽNL 25/26"
    m = re.match(r"(.+?)\s*-\s*(.+?)\s+(\d+):(\d+),\s*(.+)", title)
    if not m:
        raise RuntimeError(f"Unexpected match title format: {title!r}")

    home_team, away_team, home_score, away_score, competition = m.groups()
    return {
        "home_team": home_team.strip(),
        "away_team": away_team.strip(),
        "home_score": int(home_score),
        "away_score": int(away_score),
        "competition": competition.strip(),
    }


def _parse_datetime_and_venue(soup: BeautifulSoup):
    """
    Example line (as seen in the rendered text):
        'Močni Laz, Vela Luka, 23.11.2025. 13:30'
    We'll parse:
        venue = 'Močni Laz'
        city  = 'Vela Luka'
        date_time = datetime(...)
    """
    text_nodes = soup.find_all(string=DATETIME_RE)
    if not text_nodes:
        return None, None, None

    s = text_nodes[0].strip()
    m = DATETIME_RE.search(s)
    if not m:
        return None, None, None

    date_part, time_part = m.groups()
    dt = datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y. %H:%M")

    # Everything before the date/time is location info, usually "venue, city"
    before = s[:m.start()].rstrip(", ").strip()
    venue = None
    city = None
    if before:
        parts = [p.strip() for p in before.split(",")]
        if len(parts) == 1:
            venue = parts[0]
        elif len(parts) >= 2:
            venue = parts[0]
            city = parts[1]

    return venue, city, dt


def _parse_goals_block(soup: BeautifulSoup, teams: Dict[str, str]) -> List[GoalEvent]:
    """
    There is a compact goals summary near the top, which (in text) looks like:

        Bruno Berković
        14'
        Goran Rubeša
        27'
        ...

    We'll scan a region near the referees text ("Suci:") and treat each
    (player_name, minute) pair as one goal event.
    """
    goals: List[GoalEvent] = []

    # Find the node containing 'Suci:' (referees)
    referees_node = soup.find(string=lambda t: isinstance(t, str) and "Suci:" in t)
    if not referees_node:
        return goals

    # The goals list is shortly after that element. We'll walk forward
    current = referees_node.parent
    # Collect a small number of following strings to keep things safe
    candidates: List[str] = []
    seen = 0

    while current and seen < 120:  # arbitrary safety limit
        for t in current.stripped_strings:
            candidates.append(t)
        current = current.next_sibling if isinstance(current, Tag) else current.parent.next_sibling
        seen += 1

    # Now parse candidate strings into (name, minute) pairs
    last_name: Optional[str] = None
    for token in candidates:
        m = GOAL_MINUTE_RE.fullmatch(token)
        if m and last_name:
            minute = int(m.group(1))
            goals.append(GoalEvent(team="", player=last_name, minute=minute))
            last_name = None
        elif not GOAL_MINUTE_RE.fullmatch(token) and not token.startswith("Suci"):
            # Very naive: treat as name if it's not just a minute
            last_name = token

    # We now know who scored and when, but not which team.
    # We'll assign team later once we've parsed lineups.
    return goals


def _iterate_team_blocks(soup: BeautifulSoup) -> List[Tag]:
    """
    Team blocks (lineups) come after a small list of team names, and each
    contains:
      - a team name heading
      - shirt numbers
      - player cards (image + h3 + minutes etc.)
    In the HTML this is usually two distinct blocs (one per team).

    Here we simply search for headings that look like team names and then
    walk around them. You may want to tighten this once you can see the
    real HTML (e.g. by using a specific CSS class).
    """
    # Heuristic: find all headings that match a known team name from the H1.
    h1 = soup.find("h1")
    if not h1:
        return []

    title = h1.get_text(" ", strip=True)
    # Extract team names roughly
    m = re.match(r"(.+?)\s*-\s*(.+?)\s+\d+:\d+", title)
    if not m:
        return []

    home_name, away_name = m.group(1).strip(), m.group(2).strip()

    team_blocks: List[Tag] = []

    for team_name in (home_name, away_name):
        node = soup.find(string=lambda t: isinstance(t, str) and t.strip() == team_name)
        if not node:
            continue
        # We'll take the parent container as the team block root
        # and let _parse_players_from_team_block handle the details.
        team_blocks.append(node.parent)

    return team_blocks


def _parse_players_from_team_block(team_block: Tag) -> List[PlayerInfo]:
    """
    Parse players for one team from the corresponding DOM block.

    From the rendered text we know each player appears roughly like:

        <img ...>
        <h3><a>Player Name</a></h3>  or <h3>Player Name</h3>
        Vratar / Igrač
        [some list items with numbers and minute icons]

    We'll:
      - treat every <h3> inside this block as a player
      - look just under that <h3> for position and per-player events.
    """
    players: List[PlayerInfo] = []

    for h3 in team_block.find_all("h3"):
        name_text = h3.get_text(" ", strip=True)

        is_captain = "(C)" in name_text
        name_text = name_text.replace("(C)", "").strip()

        # Shirt number often appears close to player card, e.g. in a sibling with a small integer.
        shirt_number = None
        # Look backward a bit for a small integer
        prev_texts = list(h3.find_all_previous(string=True, limit=3))
        for t in reversed(prev_texts):
            t = t.strip()
            if t.isdigit():
                shirt_number = int(t)
                break

        # Position is often in the next tag (Vratar / Igrač)
        position = None
        nxt = h3.find_next_sibling()
        while nxt and isinstance(nxt, Tag) and not nxt.get_text(strip=True):
            nxt = nxt.find_next_sibling()
        if isinstance(nxt, Tag):
            pos_text = nxt.get_text(" ", strip=True)
            if pos_text:
                position = pos_text

        # Player events: minutes like "60'", "85'", etc appearing after h3
        events: List[PlayerEvent] = []
        scan_node = h3
        # Scan forward until the next h3 (next player card) or end of this team block
        for sib in h3.next_siblings:
            if isinstance(sib, Tag) and sib.name == "h3":
                break  # next player
            if isinstance(sib, Tag):
                for t in sib.stripped_strings:
                    m = GOAL_MINUTE_RE.fullmatch(t)
                    if m:
                        events.append(PlayerEvent(minute=int(m.group(1)), raw=t))

        # Determine if starting or on bench heuristically:
        # There is a "Pričuvni igrači" heading between starters and bench players.
        is_starting = True
        bench_marker = team_block.find(string=lambda t: isinstance(t, str) and "Pričuvni igrači" in t)
        if bench_marker and bench_marker.parent and bench_marker.parent.find_all("h3"):
            # If this player's h3 comes after bench_marker in document order, mark as bench
            if bench_marker.parent in h3.find_all_previous():
                is_starting = False

        players.append(
            PlayerInfo(
                name=name_text,
                shirt_number=shirt_number,
                position=position,
                is_captain=is_captain,
                is_starting=is_starting,
                events=events,
            )
        )

    return players


def _attach_goal_teams(goals: List[GoalEvent], lineups: Dict[str, List[PlayerInfo]]):
    """Using lineups, assign each goal to a team."""
    # Build map player_name -> team
    player_to_team: Dict[str, str] = {}
    for team, plist in lineups.items():
        for p in plist:
            player_to_team.setdefault(p.name, team)

    for g in goals:
        if g.player in player_to_team:
            g.team = player_to_team[g.player]
        else:
            g.team = "Unknown"


def scrape_match(url: str) -> MatchData:
    soup = _get_soup(url)

    header = _parse_header_info(soup)
    venue, city, dt = _parse_datetime_and_venue(soup)

    goals = _parse_goals_block(
        soup, {"home": header["home_team"], "away": header["away_team"]}
    )

    # Parse lineups (two team blocks)
    team_blocks = _iterate_team_blocks(soup)
    lineups: Dict[str, List[PlayerInfo]] = {
        header["home_team"]: [],
        header["away_team"]: [],
    }

    print(f"Home team block: {team_blocks[0]}")
    # Heuristic: first block -> home, second -> away
    if len(team_blocks) >= 1:
        lineups[header["home_team"]] = _parse_players_from_team_block(team_blocks[0])
    if len(team_blocks) >= 2:
        lineups[header["away_team"]] = _parse_players_from_team_block(team_blocks[1])

    # Attach teams to goals
    _attach_goal_teams(goals, lineups)

    # TODO (once you inspect raw HTML):
    #   - add _parse_cards(soup) to detect yellow/red based on icon CSS classes
    #   - add _parse_substitutions(soup) to detect subs (player_in / player_out)
    # At that point you can map those back to PlayerInfo.events by minute.

    return MatchData(
        url=url,
        competition=header["competition"],
        home_team=header["home_team"],
        away_team=header["away_team"],
        home_score=header["home_score"],
        away_score=header["away_score"],
        venue=venue,
        city=city,
        date_time=dt,
        goals=goals,
        lineups=lineups,
    )


if __name__ == "__main__":
    test_url = "https://semafor.hns.family/utakmice/101386217/nk-orebic-onk-metkovic-4-5/"
    data = scrape_match(test_url)

    # Pretty-print as JSON
    def serialize(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "__dict__"):
            return asdict(obj)
        raise TypeError(f"Type not serializable: {type(obj)}")

    print(json.dumps(asdict(data), default=serialize, ensure_ascii=False, indent=2))
