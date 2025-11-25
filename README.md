### Initial scoring system

| Category | Applicable to | Points | Condition |
|----------|---------------|--------|-----------|
| Appearance | Any position | 1 point | when played up to 59 minutes |
| | | 2 points | when played up to 60 minutes or more |
| Goal | Forwards | 4 points | when scored goal |
| | Midfielders | 5 points | when scored goal |
| | Defenders<br>Goalkeepers | 6 points | when scored goal |
| Assist | Any position | 3 points | when assisted for a goal |
| Clean Sheet | Midfielders | 1 point | when team concedes 0 goals and player played 60+ minutes |
| | Defenders<br>Goalkeepers | 4 points | when team concedes 0 goals and player played 60+ minutes |
| Save | Goalkeeper | 1 point | for each 3 saves made |
| Penalty | Goalkeeper | 5 points | when saved penalty |
| | Any position | -2 points | when missed penalty |
| Goal conceded | Defenders & Goalkeepers | -1 point | for every 2 goals conceded |
| Own goal | Any position | -2 points | when scored an own goal |
| Cards | Any position | -1 point | when earned a yellow card |
| | | -3 points | when earned a red card |
| Bonuses | Any position | 3 points | for best scoring individual that round |
| | | 2 points | for second best scoring individual that round |
| | | 1 point | for third best scoring individual that round |



### Requirements

#### What info do I need from every match?

- Home team
- Away team
- Match date
- Match time
- Match score
- Team lineups
- Position for each player
- Timestamp of substitutes
- Who came in and who got off in substitute
- Who scored a goal and when
- Whether the goal was a penalty or not
- The outcome of the penalty (scored, missed, saved)
- Whether the goal was an own goal or not
- Whether the player earned a yellow or red card or not


#### General flow

- Fetch data about every match from the API
    - calculate the points for each individual player based on the match events
    - update team squads with the calculated points
    - refresh the rankings based on the calculated points
    - fetch data about upcoming matches from the API