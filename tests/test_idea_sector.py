from tradehub.portfolio.sectors import idea_sector, sector_for


def test_an_idea_reads_as_the_sector_most_of_its_names_are_in():
    assert idea_sector(["TSM", "INTC", "TXN"]) == "Technology"
    assert idea_sector(["DLTR", "DG", "MO", "WSM"]) == "Consumer Staples"


def test_the_broad_market_core_never_names_the_bet():
    assert idea_sector(["SPY", "MU"]) == "Technology"
    assert idea_sector(["SPY"]) == "Broad Market"


def test_ties_go_to_the_first_name_and_nothing_reads_other():
    assert idea_sector(["XLRE", "DBC"]) == "Real Estate"
    assert idea_sector([]) == "Other"


def test_new_names_are_mapped():
    assert sector_for("MRVL") == "Technology" and sector_for("IBIT") == "Crypto" and sector_for("EEM") == "International"
