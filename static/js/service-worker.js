self.addEventListener("install", function (event) {
    console.log("FlashCards service worker installed.");
    self.skipWaiting();
});

self.addEventListener("activate", function (event) {
    console.log("FlashCards service worker activated.");
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
    let data = {};

    if (event.data) {
        try {
            data = event.data.json();
        } catch (error) {
            data = {
                title: "FlashCards",
                body: event.data.text()
            };
        }
    }

    const title = data.title || "FlashCards";
    const options = {
        body: data.body || "You have cards to review.",
        icon: "/static/favicon/android-chrome-192x192.png",
        badge: "/static/favicon/favicon-32x32.png"
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();

    event.waitUntil(
        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        }).then(function (clientList) {
            for (const client of clientList) {
                if (client.url.includes("/") && "focus" in client) {
                    return client.focus();
                }
            }

            if (clients.openWindow) {
                return clients.openWindow("/");
            }
        })
    );
});