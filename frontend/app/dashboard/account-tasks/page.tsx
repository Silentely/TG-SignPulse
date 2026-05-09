"use client";

import { Suspense } from "react";
import AccountTasksContent from "./AccountTasksContent";
import { PageLoader } from "../../../components/page-loader";
import { useLanguage } from "../../../context/LanguageContext";

export default function AccountTasksPage() {
    const { t } = useLanguage();
    return (
        <Suspense fallback={<div className="min-h-screen px-4"><PageLoader label={t("loading")} /></div>}>
            <AccountTasksContent />
        </Suspense>
    );
}
