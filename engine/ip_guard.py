"""Copyright / trademark guard for AI picture prompts (owner 20 Nov: "avoid the strikes and any violations").

Film, game and pop-culture topics (Avengers: Doomsday, GTA 6, The Shining...) made the storyboard writer describe the
franchise's own characters ("Doctor Doom in his green cloak and metal mask"), and the picture model then draws a
copyrighted character: a takedown/strike risk on every platform, and against the owner's rule "no copyrighted
characters". Every prompt that goes to a picture model passes `scrub()`: protected names are replaced with neutral
words and the prompt asks for an original design. The storyboard writer gets RULE, so it rarely writes them at all.
This is a safety net, not a full list: the writer rule and the picture check do the main work.

Only UNAMBIGUOUS names are listed: everyday words that are also characters (predator, venom, sonic boom, the Moon's
terminator line, "a marvel of engineering", "among us", electrical transformers, penny-wise) must never be touched,
or wildlife, space and money prompts would break."""
from __future__ import annotations

import re

RULE = ("Copyright and likeness (every channel): never show copyrighted or trademarked characters, costumes, masks, "
        "logos, vehicles or props from films, TV, comics, cartoons or games, and never a real actor, celebrity or "
        "athlete's face. Show ORIGINAL stand-ins instead (an unnamed hooded figure, a generic superhero silhouette, a "
        "film reel, an empty cinema, a director's chair, a game controller, a city at night) and describe them "
        "without any franchise name.")

ORIGINAL = ("original design, not resembling any existing film, comic, cartoon or game character, "
            "no real person's likeness")
NEUTRAL = "an unnamed original subject"

_NAMES = [
    # Marvel
    "avengers", "doctor doom", "dr\\.? doom", "iron man", "tony stark", "spider-?man", "peter parker",
    "captain america", "thor odinson", "the incredible hulk", "the hulk", "thanos", "black panther", "black widow",
    "wolverine", "x-men", "deadpool", "doctor strange", "scarlet witch", "wanda maximoff", "ant-man",
    "fantastic four", "galactus", "groot", "rocket raccoon", "guardians of the galaxy", "nick fury", "marvel studios",
    "marvel comics", "mcu",
    # DC
    "batman", "bruce wayne", "superman", "clark kent", "wonder woman", "the joker", "harley quinn", "aquaman",
    "green lantern", "justice league", "catwoman", "lex luthor", "batmobile", "dc comics",
    # Star Wars / sci-fi
    "darth vader", "yoda", "baby yoda", "grogu", "jedi", "sith lord", "stormtroopers?", "lightsabers?",
    "mandalorian", "chewbacca", "r2-?d2", "c-?3po", "star wars", "star trek", "xenomorph", "t-800",
    # Disney / Pixar / DreamWorks / kids
    "mickey mouse", "minnie mouse", "donald duck", "queen elsa", "anna and elsa", "simba", "mufasa",
    "buzz lightyear", "lightning mcqueen", "finding nemo", "shrek", "despicable me", "spongebob", "patrick star",
    "peppa pig", "bluey", "cocomelon", "dora the explorer", "paw patrol", "barbie", "optimus prime", "teletubbies",
    "sesame street", "winnie the pooh", "tom and jerry", "scooby-?doo", "pok[eé]mon", "pikachu", "hello kitty",
    "doraemon", "chhota bheem", "motu patlu", "shin-?chan",
    # Games
    "super mario", "princess peach", "legend of zelda", "sonic the hedgehog", "pac-?man", "master chief", "kratos",
    "lara croft", "fortnite", "minecraft", "roblox", "call of duty", "grand theft auto", "gta(?: ?(?:vi|v|iv|\\d))?",
    "rockstar games", "vice city", "trevor philips", "niko bellic",
    # Fantasy / TV / film
    "harry potter", "hermione granger", "voldemort", "hogwarts", "gandalf", "frodo", "gollum", "sauron",
    "game of thrones", "daenerys", "stranger things", "squid game", "katniss", "hunger games", "james bond",
    "indiana jones", "jack sparrow", "godzilla", "jurassic park", "jack torrance", "hannibal lecter",
    "freddy krueger", "jason voorhees", "pennywise the clown", "chucky doll", "ghostface", "overlook hotel",
    "wednesday addams",
    # Anime studios and shows (owner 21 Nov: long story series in a hand-painted anime look, P3s). The LOOK is
    # described with style words (hand-painted anime, watercolour backgrounds, soft light); a studio's name, its
    # director's name or its films/characters never go into a title, tag, description or picture prompt.
    "(?:studio )?ghibli(?:[- ]?(?:style|styled|esque|fied|like|inspired|art|anime))?", "hayao miyazaki",
    "miyazaki[- ](?:style|styled|inspired|film|films|movie|movies|anime)", "(?:in )?the style of miyazaki",
    "totoro", "my neighbou?r totoro", "princess mononoke", "howl'?s moving castle", "kiki'?s delivery service",
    "ponyo", "nausica[aä] of the valley", "porco rosso", "arrietty", "the boy and the heron",
    "grave of the fireflies", "chihiro ogino", "makoto shinkai", "kimi no na wa", "kimetsu no yaiba",
    "demon slayer anime", "tanjiro kamado", "naruto uzumaki", "naruto shippuden", "naruto anime", "dragon ball(?: z)?",
    "attack on titan", "sailor moon", "jujutsu kaisen", "my hero academia", "one piece anime", "monkey d\\.? luffy",
    # NOT listed on purpose: Naruto (a Japanese city and its whirlpools), "demon slayer" (Durga in Hindu myth),
    # Son Goku / Sun Wukong (Journey to the West, public domain), Laputa (Gulliver's Travels), "castle in the sky"
]
_RX = re.compile(r"(?<![\w-])(" + "|".join(_NAMES) + r")(?![\w-])", re.I)


def hits(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _RX.finditer(text or "")})


def scrub(prompt: str) -> tuple[str, list[str]]:
    """(safe prompt, protected names found). Names become a neutral phrase and the prompt asks for an original
    design. Prompts without hits come back unchanged."""
    found = hits(prompt)
    if not found:
        return prompt, []
    clean = _RX.sub(NEUTRAL, prompt)
    clean = re.sub(rf"({NEUTRAL})(?:[\s,'’s]+{NEUTRAL})+", r"\1", clean, flags=re.I)
    return f"{clean}, {ORIGINAL}", found
