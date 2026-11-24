# GitHub, in plain language

Your **repository** is the public home for `fun`: its code, README, and history. **Git** is the tool that records changes on your computer and sends them to GitHub.

## Getting a copy

**Cloning** makes a local copy that stays connected to the GitHub repository:

```bash
git clone https://github.com/Slavro-1/fun.git
cd fun
```

People can then run `./install.sh`, or try `./fun --scene aurora` first. Someone without Git can use **Code → Download ZIP** on GitHub, extract it, open a terminal in the `fun-main` folder, and run `bash install.sh`. A ZIP is just a snapshot; it has no Git connection for updates.

## Saving and publishing your changes

A **commit** is a named checkpoint in the project history. **Pushing** sends local commits to GitHub. From your `fun` checkout:

```bash
git status
git add README.md assets docs/GITHUB_GUIDE.md
git commit -m "Refresh project presentation"
git push origin main
```

Use `git status` to see what changed before adding files. Add the actual files you changed; the example above is for a README and gallery update. `main` is the normal development branch. `origin` is the saved name for your GitHub repository.

To bring a different clone up to date later, run `git pull origin main` from that clone. If you have uncommitted work there, save or commit it first.

## Versions and releases

A **tag** points to one exact commit. Your existing `v0.1.0` tag stays on its original commit. A **GitHub Release** is a public version page built around a tag; it can include notes and downloadable assets. `main` keeps moving as you make new commits, while old tags stay put.

When a new version is ready, check the project, commit the version's final changes, then create a *new* tag and push it. For example, if the next version really is 0.1.1:

```bash
git status
git tag v0.1.1
git push origin main
git push origin v0.1.1
```

Then open **Releases → Draft a new release** on GitHub, select `v0.1.1`, write a short summary, and publish it. Do not reuse or move `v0.1.0`.

## Feedback from other people

People can open an **Issue** to report a bug or ask a question. Ask them what command they ran, what happened, what they expected, and which terminal and Linux setup they used. A **pull request** is a proposed change from someone else's branch or fork. You can review its code and discussion before merging it into `main`.
