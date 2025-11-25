from ScraperFC import sofascore as sfc

ss = sfc.Sofascore()
player_data = ss.scrape_player_league_stats("25/26", "ZNLDN")
player_dict = player_data.to_dict('records')
print(player_dict)




