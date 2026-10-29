'use client';

import { useState } from 'react';
import { useRouter } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';
import {
    StatsCard,
    StatsCardsCarousel,
    SearchBarDropdown,
    SearchBar,
} from '@/components/ui';
import { getTasksListPath } from '@/features/approval/utils/taskNavigation';

import { useRegister } from '@/context/RegisterContext';
import { useRuntimeConfig } from '@/context/RuntimeConfigContext';

import {
    REGISTER_ACTIONS,
    INTAKE_FORM_ACTIONS,
    CHANGE_REQUEST_ACTIONS,
    INCOMING_MESSAGE_ACTIONS,
    OUTGOING_MESSAGE_ACTIONS,
    VERIFICATION_CHANGE_REQUEST_ACTIONS,
    VERIFICATION_INTAKE_FORM_ACTIONS,
} from '@/features/shared/permissions';
import { TASK_ARTIFACT_FILTER_OPTIONS } from '@/features/approval/constants';
import Can from '@/components/shared/Can';


type ActiveStatsCard =
    | 'registers'
    | 'form-submissions'
    | 'change-request'
    | 'messages'
    | 'tasks';

const STATS_CARDS: ActiveStatsCard[] = [
    'registers',
    'form-submissions',
    'change-request',
    'tasks',
    'messages',
];

export default function Home() {
    const router = useRouter();
    const t = useTranslations();
    const { config } = useRuntimeConfig();

    const [activeStatsCard, setActiveStatsCard] =
        useState<ActiveStatsCard>('registers');
    const [selectedRegister, setSelectedRegister] = useState('select');
    const [selectedMessageType, setSelectedMessageType] = useState('incoming');
    const [selectedTaskArtifact, setSelectedTaskArtifact] = useState('change_request');

    const messageTypeOptions = [
        { value: 'incoming', label: t('incoming_messages') },
        { value: 'outgoing', label: t('outgoing_messages') },
    ];


    const { registers } = useRegister();

    const registerList =
        registers.map(r => ({
            value: r.register_mnemonic.toLowerCase(),
            label: t(r.register_subject),
        }));

    const taskArtifactOptions = TASK_ARTIFACT_FILTER_OPTIONS.map((opt) => ({
        value: opt.value,
        label:
            opt.value === 'change_request'
                ? t('change_requests')
                : t('form_submissions'),
    }));

    const searchPlaceholders: Record<ActiveStatsCard, string> = {
        'registers': t('search_registers'),
        'form-submissions': t('search_form_submissions'),
        'change-request': t('search_change_requests'),
        'messages': t('search_messages'),
        'tasks': t('search_approval_tasks'),
    };

    const getCardPath = (
        card: ActiveStatsCard,
        register?: string,
    ): string | null => {
        if (card === 'registers' || card === 'form-submissions') {
            const selected =
                (register && register !== 'select' && register)
                || (selectedRegister !== 'select' && selectedRegister)
                || registerList[0]?.value;

            if (!selected) return null;

            return card === 'registers'
                ? `/register/${selected}`
                : `/intake-form/${selected}`;
        }

        if (card === 'messages') {
            return selectedMessageType === 'outgoing'
                ? '/outgoing-messages'
                : '/incoming-messages';
        }

        if (card === 'tasks') {
            return getTasksListPath(
                selectedTaskArtifact as 'change_request' | 'intake_form',
            );
        }

        return '/change-request';
    };

    const handleSearch = (value: string, register?: string) => {
        const searchValue = value.trim();
        const basePath = getCardPath(activeStatsCard, register);
        if (!basePath) return;

        const params = new URLSearchParams();
        if (searchValue) {
            params.set('search', searchValue);
        }
        params.set('page', '1');

        const query = params.toString();
        router.push(query ? `${basePath}?${query}` : basePath);
    };

    const handleCardNavigate = (card: ActiveStatsCard) => {
        const path = getCardPath(card);
        if (path) router.push(path);
    };

    const getViewAction = (
        activeStatsCard: ActiveStatsCard,
        selectedMessageType: string
    ) => {
        switch (activeStatsCard) {
            case "registers":
                return REGISTER_ACTIONS.view;
            case "form-submissions":
                return INTAKE_FORM_ACTIONS.view;
            case "change-request":
                return CHANGE_REQUEST_ACTIONS.view;
            case "messages":
                return selectedMessageType === "incoming"
                    ? INCOMING_MESSAGE_ACTIONS.view
                    : OUTGOING_MESSAGE_ACTIONS.view;
        }
    };

    const viewAction = getViewAction(activeStatsCard, selectedMessageType);
    const taskSearchAnyOf = [
        VERIFICATION_CHANGE_REQUEST_ACTIONS.create,
        VERIFICATION_INTAKE_FORM_ACTIONS.create,
    ];

    const statsEndpointFor = (type: ActiveStatsCard) => {
        const endpointByType: Record<ActiveStatsCard, string> = {
            registers: 'register',
            'form-submissions': 'intake-form',
            'change-request': 'change-request',
            messages: 'incoming-messages',
            tasks: 'tasks',
        };
        return `/api/stats/${endpointByType[type]}`;
    };

    const useStatsCarousel = STATS_CARDS.length > 4;
    const dashboardImage = config.branding?.dashboard_image;

    return (
        <div
            className="min-h-[calc(100vh-4.375rem)] bg-primary-first bg-cover bg-center bg-no-repeat pt-8 sm:pt-10 md:pt-12 overflow-hidden text-secondary-second-900"
            style={{ backgroundImage: dashboardImage ? `url(${JSON.stringify(dashboardImage)})` : 'none' }}
        >
            <div className="relative">
                <div className="mx-auto flex max-w-6xl flex-col items-center px-4 sm:px-6 py-8 sm:py-10 lg:py-12 space-y-10 sm:space-y-12 lg:space-y-14">

                    {/* stats cards */}
                    {useStatsCarousel ? (
                        <StatsCardsCarousel
                            cards={STATS_CARDS}
                            activeCard={activeStatsCard}
                            onSelectCard={setActiveStatsCard}
                            onNavigateCard={handleCardNavigate}
                            StatsCardComponent={StatsCard}
                            statsEndpointFor={statsEndpointFor}
                        />
                    ) : (
                        <div className="flex w-full flex-wrap items-stretch justify-center gap-4 sm:gap-5 lg:gap-6">
                            {STATS_CARDS.map((type) => (
                                <div
                                    key={type}
                                    className="flex-1 min-w-40 sm:min-w-45 lg:min-w-55"
                                >
                                    <StatsCard
                                        stats_endpoint={statsEndpointFor(type)}
                                        active={activeStatsCard === type}
                                        onSelect={() => setActiveStatsCard(type)}
                                        onNavigate={() => handleCardNavigate(type)}
                                    />
                                </div>
                            ))}
                        </div>
                    )}
                    <Can
                        action={activeStatsCard === 'tasks' ? undefined : viewAction}
                        anyOf={activeStatsCard === 'tasks' ? taskSearchAnyOf : undefined}
                        fallback={
                            <div className="relative border border-primary-second flex h-14 w-4/5 items-center rounded-[10px] bg-neutral-second overflow-visible">
                                <div className="relative flex items-center w-full h-full">
                                    <SearchBar
                                        placeholder={searchPlaceholders[activeStatsCard]}
                                        category={selectedRegister}
                                        onSearch={() => { }}
                                    />
                                    <div className="absolute inset-0 z-10 cursor-not-allowed" />
                                </div>
                            </div>
                        }
                    >
                        <div className="relative border border-primary-second flex h-14 w-4/5 items-center rounded-[10px] bg-neutral-second overflow-visible">

                            {(activeStatsCard === 'registers' || activeStatsCard === 'form-submissions') &&
                                registerList?.length > 0 && (
                                    <SearchBarDropdown
                                        options={registerList}
                                        selected={selectedRegister}
                                        onChange={setSelectedRegister}
                                    />
                                )}

                            {activeStatsCard === 'messages' && (
                                <SearchBarDropdown
                                    options={messageTypeOptions}
                                    selected={selectedMessageType}
                                    onChange={setSelectedMessageType}
                                />
                            )}

                            {activeStatsCard === 'tasks' && (
                                <SearchBarDropdown
                                    options={taskArtifactOptions}
                                    selected={selectedTaskArtifact}
                                    onChange={setSelectedTaskArtifact}
                                />
                            )}

                            <SearchBar
                                placeholder={searchPlaceholders[activeStatsCard]}
                                category={selectedRegister}
                                onSearch={handleSearch}
                            />
                        </div>
                    </Can>
                </div>
            </div>
        </div>
    );
}
