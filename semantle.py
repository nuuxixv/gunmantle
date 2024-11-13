import pickle
import os
import random
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import (
    Flask,
    send_file,
    send_from_directory,
    jsonify,
    render_template
)
from pytz import utc, timezone

import word2vec
from process_similar import get_nearest

KST = timezone('Asia/Seoul')

NUM_SECRETS = 4650
FIRST_DAY = date(2022, 4, 1)
SECRETS_PATH = 'data/secrets.txt'

scheduler = BackgroundScheduler()
scheduler.start()

app = Flask(__name__)

def get_today_word():
    """
    secrets.txt 파일에서 오늘의 단어를 읽어옵니다.
    파일의 첫 줄에 '# today_word: 원하는단어' 형식으로 지정됩니다.
    """
    today_word = None
    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('# today_word:'):
                    today_word = line.split(':', 1)[1].strip()
                    break
    return today_word

def get_secret_words():
    """
    secrets.txt 파일에서 주석을 제외한 모든 단어 목록을 반환합니다.
    """
    words = []
    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#'):
                    continue  # 주석은 무시
                if line:
                    words.append(line)
    return words

# 오늘의 단어 설정
TODAY_WORD = get_today_word()
secrets = get_secret_words()

if TODAY_WORD:
    # 오늘의 단어가 설정된 경우, 해당 단어를 리스트의 첫 번째로 이동
    if TODAY_WORD in secrets:
        secrets.remove(TODAY_WORD)
    secrets.insert(0, TODAY_WORD)
else:
    # 오늘의 단어가 설정되지 않은 경우, 랜덤으로 선택
    TODAY_WORD = random.choice(secrets) if secrets else "default"

print("loading valid nearest")
with open('data/valid_nearest.dat', 'rb') as f:
    valid_nearest_words, valid_nearest_vecs = pickle.load(f)

print("initializing nearest words for solutions")
app.secrets = dict()
app.nearests = dict()
current_puzzle = (utc.localize(datetime.utcnow()).astimezone(KST).date() - FIRST_DAY).days % NUM_SECRETS

for offset in range(-2, 2):
    puzzle_number = (current_puzzle + offset) % NUM_SECRETS
    if puzzle_number < len(secrets):
        secret_word = secrets[puzzle_number]
    else:
        secret_word = "default"
    app.secrets[puzzle_number] = secret_word
    app.nearests[puzzle_number] = get_nearest(puzzle_number, secret_word, valid_nearest_words, valid_nearest_vecs)


@scheduler.scheduled_job(trigger=CronTrigger(hour=1, minute=0, timezone=KST))
def update_nearest():
    print("scheduled stuff triggered!")
    next_puzzle = ((utc.localize(datetime.utcnow()).astimezone(KST).date() - FIRST_DAY).days + 1) % NUM_SECRETS
    if next_puzzle < len(secrets):
        next_word = secrets[next_puzzle]
    else:
        next_word = "default"
    to_delete = (next_puzzle - 4) % NUM_SECRETS
    if to_delete in app.secrets:
        del app.secrets[to_delete]
    if to_delete in app.nearests:
        del app.nearests[to_delete]
    app.secrets[next_puzzle] = next_word
    app.nearests[next_puzzle] = get_nearest(next_puzzle, next_word, valid_nearest_words, valid_nearest_vecs)


@app.route('/')
def get_index():
    return render_template('index.html')


@app.route('/robots.txt')
def robots():
    return send_file("static/assets/robots.txt")


@app.route("/favicon.ico")
def send_favicon():
    return send_file("static/assets/favicon.ico")


@app.route("/assets/<path:path>")
def send_static(path):
    return send_from_directory("static/assets", path)


@app.route('/guess/<int:day>/<string:word>')
def get_guess(day: int, word: str):
    # print(app.secrets[day])
    # remove lower(), unnecessary to korean
    if app.secrets.get(day) == word:
        word = app.secrets[day]
    rtn = {"guess": word}
    # check most similar
    if day in app.nearests and word in app.nearests[day]:
        rtn["sim"] = app.nearests[day][word][1]
        rtn["rank"] = app.nearests[day][word][0]
    else:
        try:
            rtn["sim"] = word2vec.similarity(app.secrets[day], word)
            rtn["rank"] = "1000위 이상"
        except KeyError:
            return jsonify({"error": "unknown"}), 404
    return jsonify(rtn)


@app.route('/similarity/<int:day>')
def get_similarity(day: int):
    if day not in app.nearests:
        return jsonify({"error": "unknown day"}), 404
    nearest_dists = sorted([v[1] for v in app.nearests[day].values()])
    return jsonify({"top": nearest_dists[-2], "top10": nearest_dists[-11], "rest": nearest_dists[0]})


@app.route('/yesterday/<int:today>')
def get_solution_yesterday(today: int):
    return app.secrets.get((today - 1) % NUM_SECRETS, "unknown")


@app.route('/nearest1k/<int:day>')
def get_nearest_1k(day: int):
    if day not in app.secrets:
        return "이 날의 가장 유사한 단어는 현재 사용할 수 없습니다. 그저께부터 내일까지만 확인할 수 있습니다.", 404
    solution = app.secrets[day]
    words = [
        dict(
            word=w,
            rank=k[0],
            similarity="%0.2f" % (k[1] * 100))
        for w, k in app.nearests[day].items() if w != solution]
    return render_template('top1k.html', word=solution, words=words, day=day)


@app.route('/giveup/<int:day>')
def give_up(day: int):
    if day not in app.secrets:
        return '저런...', 404
    else:
        return app.secrets[day]


if __name__ == '__main__':
    app.run(debug=True)