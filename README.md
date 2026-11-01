# Jenny's Kitchen — Phase 1–4 + Premium Storefront Upgrade

A Flask-based restaurant website for Jenny's Kitchen, Jos South, Plateau State, Nigeria. The project keeps the red/yellow brand palette and reference-inspired homepage, with customer ordering and an admin content editor.

## Included in this package

### Phase 1 — Core experience
- Responsive, red/yellow/cream homepage with configurable hero slider and featured meals.
- Menu search and category filters.
- Session cart and server-side price/availability checks during checkout.
- Delivery or pickup selection, order notes, order creation and order tracking.
- Admin menu management, homepage/brand editor, featured-meal selection, hero slide editing, contact details, delivery-fee setting, and image uploads.
- Image uploads validate file signatures and do not require Pillow/native JPEG libraries, so installation is friendlier to Termux.
- Production configuration refuses to start without `JENNY_SECRET_KEY` when `APP_ENV=production` or `FLASK_ENV=production`.
- The app does not run Flask debug mode in production.

### Phase 2 — Sales channel
- Paystack transaction initialization when configured.
- Server-side Paystack verification on callback; success requires matching reference, successful status, exact expected amount, and NGN currency.
- Paystack webhook signature validation, followed by server-side transaction verification.
- Order payment status and order status are recorded separately.
- Optional SMTP email notification for new orders and status/payment changes.
- Configurable delivery fee, promotional homepage banner, checkout discount codes, and a promotions admin page.
- Admin-configurable meal bundles can be published through Menu management as normal orderable menu items in a `Meal Bundles` or `Combos` category (bundle price and image are controlled by the admin).
- Admin order queue includes payment status and order-status controls.
- Basic order analytics in the admin dashboard.

## Run in Termux

Install the Python packages:

```bash
pkg update
pkg install python
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Set a strong admin username and password before the first database seed. The password must be at least 12 characters. These variables are used only when the database has no admin account.

```bash
export JENNY_ADMIN_USERNAME='choose-an-admin-username'
export JENNY_ADMIN_PASSWORD='replace-with-a-unique-password-of-12-characters-or-more'
python seed.py
```

Copy `.env.example` to `.env` and add your real WhatsApp number and a long random `JENNY_SECRET_KEY` before deployment. Keep `.env` out of public repositories.

Start the app:

```bash
python app.py
```

Open `http://127.0.0.1:5000`. For another device on the same Wi-Fi, use the host phone's local IP and port `5000`.

The admin login is at `/admin/login`. If an existing database already has an admin account, `seed.py` will not overwrite it. Change existing credentials using the project's admin-management procedure; do not assume changing the environment variables will change an existing account.

## Configure Paystack (test mode first)

Paystack is deliberately disabled until credentials are supplied. Without a secret key, the checkout does not offer online payment and will reject forged Paystack submissions.

Set your Paystack **test** secret key in the server environment (never put it in templates, JavaScript, Git, or the ZIP):

```bash
export PAYSTACK_SECRET_KEY='sk_test_your_key_here'
export PAYSTACK_PUBLIC_KEY='pk_test_your_key_here'
```

Restart the application after setting the variables. Checkout will initialize a transaction through Paystack and redirect the customer to the returned authorization URL. The callback endpoint is:

`https://YOUR-DEPLOYED-DOMAIN/payments/paystack/callback`

The webhook endpoint is:

`https://YOUR-DEPLOYED-DOMAIN/payments/paystack/webhook`

Configure the webhook URL in the Paystack dashboard for the deployed domain. Paystack cannot reach a localhost-only URL. For local testing, use Paystack's test environment and a publicly reachable development tunnel only if you understand the exposure risks.

**Payment verification:** the browser redirect alone never marks a payment as paid. The server calls Paystack's verification API and checks the transaction reference, success status, amount in kobo, and NGN currency. Keep test keys until all success, failure, cancellation, duplicate-callback, and webhook scenarios have been tested. Live payments have not been tested from this package environment.

## Optional order email notifications

Configure SMTP using environment variables if you want order notifications emailed to the kitchen:

```bash
export SMTP_HOST='smtp.example.com'
export SMTP_PORT='587'
export SMTP_USER='your-smtp-user'
export SMTP_PASSWORD='your-smtp-password'
export SMTP_FROM='orders@your-domain.example'
export ORDER_NOTIFICATION_EMAIL='kitchen@your-domain.example'
```

If SMTP is not configured, orders still save normally; the app logs notification failures instead of losing the order. Use an email address and SMTP service controlled by Jenny's Kitchen.

## Production security checklist

Before public launch:

1. Set `APP_ENV=production` and a long, random `JENNY_SECRET_KEY`.
2. Set `COOKIE_SECURE=1` only when the site is served over HTTPS.
3. Configure production database backups and a supported WSGI server/reverse proxy with HTTPS; do not expose Flask's development server as the production server.
4. Use live Paystack credentials only after test-mode checks and a real low-value verification run.
5. Set and verify the actual business phone, WhatsApp number, address, delivery coverage, fees, opening hours, menu prices, and meal images.
6. Create a strong administrator credential; do not use a shared or default password.
7. Configure the Paystack webhook URL and SMTP only when those services are ready.
8. Review customer-data retention and access before launch.

## Database notes

The ZIP intentionally does **not** include a live SQLite database or pre-seeded admin credentials. `python seed.py` creates the tables and menu records. It creates an admin only when `JENNY_ADMIN_USERNAME` and `JENNY_ADMIN_PASSWORD` are supplied and the database has no admin. Existing databases are preserved; the app adds the new payment-related order columns when it starts.

## Verification status

Python syntax compilation and ZIP integrity were checked while preparing this package. The current execution environment did not have Flask dependencies installed and package downloads were unavailable, so I could not run browser-based or end-to-end tests here. Paystack also requires Jenny's own API keys and a publicly reachable deployed callback/webhook URL; live payment verification is therefore not claimed as tested. Please follow the test-mode checklist before taking real customer orders.

## Phase 3 — customer relationships

- Customer account page with order history, saved favourites, repeat-order action, loyalty ledger, review submission, and marketing preference controls.
- Loyalty earns **1 point per ₦1,000** when a signed-in customer's order is marked delivered. Every **100 points saves ₦500** on the food subtotal after promotion discounts. Redeemed points are restored if an order is cancelled.
- Referral rewards are issued after the referred customer's first delivered order: **100 bonus points to each customer**. Share the referral code at signup; rewards should be reviewed against actual operating costs before launch.
- Reviews require a signed-in account and a delivered order containing the meal. They remain unpublished until an admin approves them.
- The existing WhatsApp contact link remains the support channel. Optional SMTP sends transactional order status updates; marketing campaigns are separate and only go to customers who opted in.
- Customers can unsubscribe from promotional email with a unique token link or switch consent off in their account.

## Phase 4 — brand, publishing, SEO and measurement

- Website Studio now links to a safe page editor with a live text preview, draft/publish control, URL slug validation, and escaped plain-text content (no arbitrary HTML or scripts).
- `/sitemap.xml` and `/robots.txt` are generated automatically. The base layout includes canonical URLs and Restaurant structured data; the menu includes structured Menu/MenuSection/MenuItem data with NGN prices.
- Optional first-party analytics record a small allowlist of events only after the visitor accepts analytics. No IP address, email address, order number, or raw customer ID is stored. Rejecting analytics leaves ordering available.
- Add `utm_campaign` to campaign links to attribute page views, add-to-cart activity and campaign clicks. Review totals in Admin → Analytics.
- Uploaded images have unique filenames and receive long-lived static cache headers. Menu imagery is lazy-loaded and asynchronously decoded. Continue to use appropriately sized, compressed images for best mobile performance.

## Premium storefront upgrade

- Reference-led visual refresh with cinematic cross-fading hero slides, warm cream surfaces, vivid red calls to action, yellow accents, food-led cards and responsive horizontal meal carousels.
- Mobile-first navigation with an explicit Reserve a table link; customer navigation is separated from the admin workspace.
- Add-to-cart now uses a single asynchronous request, updates the bag count, and reveals a floating “Checkout now” prompt for approximately four seconds. Recoverable network and availability messages replace generic alerts.
- Table reservation requests save to the database with a reference number;
- Admin-configurable delivery areas/landmarks, rider fees and ETA ranges; checkout selects the nearest configured area and saves its quoted fee/time on the order; the admin workspace can confirm, seat, complete or cancel requests. A request is clearly described as pending until the team confirms it.
- Admin menu availability supports Available, Temporarily unavailable, Sold out today and Hidden from menu. Existing availability data is migrated additively.
- Checkout promotion validation now gives immediate eligibility feedback and shows the discount in the order summary before order submission.
- Admin pages use a dedicated sidebar and a clear “View customer storefront” link to switch between admin and customer experiences.
- Newsletter drafting/sending, campaign opt-in, loyalty, customer reorder, favorites, review moderation, discounts and analytics from Phase 3/4 remain in place.
- `JENNY_WHATSAPP_NUMBER` is supported from `.env`; copy `.env.example` to `.env`, add the WhatsApp number in international digits (for Nigeria, e.g. `23480…`), and keep `.env` private. `python-dotenv` loads the file at startup.

## Phase 3/4 setup and launch checks

The additions are designed to be additive for existing SQLite installations: startup/seed migration adds missing columns and does not intentionally erase existing orders or users. Back up the database before upgrading. Re-run `python seed.py` after replacing the code so new tables are created and old tables receive additive columns.

Before launch, manually verify: signup/login; consent opt-in/out and unsubscribe; favourites; reorder; delivered-order reviews and admin moderation; loyalty earning/redeeming/cancellation refund; referral rewards; order emails; campaign sends using a small internal test list; page draft/publish; sitemap/robots; analytics accepted/rejected; and checkout/payment test cases from Phase 2.

**Testing limitation:** Python syntax compilation and ZIP integrity were checked while preparing this package. A full live Flask/database/browser run, database migration against your actual live database, SMTP campaign delivery, and Paystack end-to-end test could not be executed in this environment. Test against a backup and use Paystack test keys before launch. Do not treat this as a claim of zero defects or production certification; run the checklist with a backup and Paystack test keys before taking real orders.


## New admin and operations notes

- Table reservations are requests, not instant confirmed bookings. Admin must confirm the date/time and seating capacity with the customer.
- Meal bundles can be added as normal menu items in the `Combos` or `Meal Bundles` category as described in Phase 2; the separate `MealBundle` data model is prepared for a future bundle-builder interface.
- Delivery landmarks, route tariffs and delivery ETA are deliberately not pre-filled because Jenny's Kitchen must confirm the exact serviceable Jos South locations, pickup point, current rider rates and delivery-time rules. Configure verified areas and fees in Admin → Delivery areas & fees before enabling delivery checkout. No location or fee is guessed.
- Welcome offers and seasonal referral campaigns are administered using the existing Promotions and Campaigns areas. Create a first-order code (for example, WELCOME) and communicate its eligibility/expiry to customers; the code is not automatically issued by default.


## Official brand identity and responsive navigation update

- The official Jenny's Kitchen chef mascot logo is installed as `static/images/jennys-kitchen-logo.png` (transparent, upscaled PNG master).
- The logo is used in the customer header, storefront footer, admin workspace, loading screen, browser favicon, Apple touch icon and PWA icons.
- The admin workspace uses a fixed, single-column desktop sidebar. At tablet and phone widths it becomes an accessible slide-out drawer with backdrop, close-on-navigation, Escape-key support and scroll locking.
- Customer navigation stays horizontal on wide screens and becomes a compact animated dropdown on tablet/phone screens.
- The service worker cache version was incremented so browsers refresh the new brand assets.

### Validation performed for this update

- Python source compilation passed for `app.py`, `models.py` and `seed.py`.
- All 27 Jinja templates parsed successfully.
- Inline JavaScript syntax check passed.
- Template `url_for` endpoint audit found no missing endpoint names.
- ZIP archive integrity was checked after packaging.

A live Flask server, database migration and payment-provider round-trip still need to be run in the deployment environment with the dependencies and environment secrets installed.
