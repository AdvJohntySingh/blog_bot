name: Publish or reject draft

on:
  workflow_dispatch:
    inputs:
      draft_id:
        description: "Draft date, YYYY-MM-DD"
        required: true
      decision:
        description: "approve or reject"
        required: true

permissions:
  contents: write

jobs:
  apply:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install requests

      - name: Apply decision
        env:
          ID: ${{ inputs.draft_id }}
          DECISION: ${{ inputs.decision }}
          HASHNODE_TOKEN: ${{ secrets.HASHNODE_TOKEN }}
          HASHNODE_PUBLICATION_ID: ${{ secrets.HASHNODE_PUBLICATION_ID }}
        run: |
          set -e
          [[ "$ID" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "bad id"; exit 1; }
          D="drafts/$ID"
          git config user.name "blog-bot"
          git config user.email "blog-bot@users.noreply.github.com"
          if [ "$DECISION" = "approve" ]; then
            SLUG=$(jq -r .slug "$D/draft.json")
            mkdir -p images
            cp "$D/image.jpg" "images/$ID-$SLUG.jpg"
            git add images
            git commit -m "Add image $ID"
            git push
            sleep 15   # let the image link go live
            python scripts/publish_hashnode.py "$ID"
            git add published
          elif [ "$DECISION" != "reject" ]; then
            echo "bad decision"; exit 1
          fi
          git rm -rq "$D"
          git commit -m "$DECISION draft $ID"
          git push

      - name: Tell me on Telegram
        env:
          TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          CHAT: ${{ secrets.TELEGRAM_CHAT_ID }}
          DECISION: ${{ inputs.decision }}
        run: |
          if [ "$DECISION" = "approve" ]; then
            MSG="Published on Hashnode: $(cat post_url.txt)"
          else
            MSG="Draft rejected and deleted."
          fi
          curl -s "https://api.telegram.org/bot$TOKEN/sendMessage" -d chat_id="$CHAT" --data-urlencode text="$MSG"
