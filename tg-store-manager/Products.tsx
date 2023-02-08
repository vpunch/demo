import {useMemo, useState, useEffect, useCallback} from 'react';

import {useLocation, useNavigate} from 'react-router-dom';
import {animateScroll as scroll} from 'react-scroll';
import _findIndex from 'lodash-es/findIndex';
import _last from 'lodash-es/last';

import Search from './Search';
import {TRANS_DUR} from '../Screen';
import CatProds, {getCatProdsId} from '../CatProds';
import CompactCats, {getHeaderHeight} from '../CompactCats';
import Header, {HeaderWrapper} from '../Header';
import {H1_MARGIN} from '../Back';
import {getCfg} from '../../common';
import type {CatDetailsFragment} from '../../utils/graphql';
import type {GetProdCount} from '../../hooks/useCart';


export type CatOffset = {[id: string]: number};


const IS_CAT_LOADED: {[id: string]: boolean} = {};

export const getIsLoaded = () => Object.values(IS_CAT_LOADED).every(Boolean);


export default function Products({categories, store, getProdCount}: {
    categories: CatDetailsFragment[];
    store: Store;
    getProdCount: GetProdCount
}) {
    // Для категорий устанавливаются границы отображения
    // NOTE Подгружать товары сверху нельзя, браузеры не умеют адекватно
    // это обрабатывать

    // При смене хэша компонент будет обновлен, если хэш удалить, будет
    // ремаунт

    const {hash} = useLocation();  // #id | undefined

    // NOTE Может быть невалидным
    const catId = hash ? hash.slice(1) : categories[0].id;

    const catIdx = useMemo(() => {
        const idx = _findIndex(categories, ({id}) => id === catId);
        return idx === -1 ? 0 : idx;
    }, []);

    const [startIdx] = useState(getCfg().VITE_COMPACT_CATEGORIES ? 0 : catIdx);
    const [rightOffset, setRightOffset] = useState(
            getCfg().VITE_DYNAMIC_CATEGORY
                ? getCfg().VITE_COMPACT_CATEGORIES ? catIdx : 0
                : categories.length - 1);

    const [updateCounter, setUpdateCounter] = useState(0);
    // Скролом при переходе управляет менеджер
    const [needScroll,    setNeedScroll] = useState(false);
    const [catOffset,     setCatOffset] = useState<CatOffset>({});

    const [searchHeaderH, setSearchHeaderH] = useState(0);

    const getRightBound = () => startIdx + rightOffset;

    const handleScroll = useCallback(() => {
        // Подгрузка категории

        if (!getIsLoaded())
            return;

        const screenEl = document.getElementById('prods-screen')!;

        // NOTE Категория не должна быть пустой
        // Граница для подгрузки будет обновляться, чтобы учесть разный
        // размер карточек товара

        const cards = document.getElementsByClassName('prod-card')
        const card = _last(cards) as HTMLDivElement | undefined;

        const bound = card ? screenEl.scrollHeight - card.offsetHeight / 2 : 0;

        if (pageYOffset + innerHeight > bound &&
                getRightBound() < categories.length - 1)
            setRightOffset(rightOffset + 1);
    }, [rightOffset, updateCounter]);

    useEffect(() => {
        const element = document.getElementById('prods-header--search')!;
        setSearchHeaderH(element.offsetHeight);
    }, []);

    // Не дожидаемся события, если категорию уже можно подгрузить
    handleScroll();

    useEffect(() => {
        addEventListener('scroll', handleScroll);
        return () => removeEventListener('scroll', handleScroll);
    }, [handleScroll]);

    useEffect(() => {
        // Обновление позиций категорий

        if (!getIsLoaded())
            return;

        // Смещения меняются из-за анимации и скролбара, который может
        // появляться на экране. Поэтому ждем полной установки экрана.
        setTimeout(() => {
            Object.keys(IS_CAT_LOADED).forEach(id => {
                const catProds = document.getElementById(getCatProdsId(id));
                // Категория может быть загружена, но не быть на
                // экране
                if (catProds) {
                    const rect = catProds.getBoundingClientRect();
                    catOffset[id] = pageYOffset + rect.top;
                }
            });

            setCatOffset({...catOffset});
        }, TRANS_DUR * 1000);
    }, [rightOffset, updateCounter]);  // расширение, либо обновление

    useEffect(() => {
        if (needScroll && getIsLoaded()) {
            const catProds = document.getElementById(getCatProdsId(catId))!;

            // Без дополнительного смещения категория не переключается
            // на мобильном клиенте
            const offset = 4;

            scroll.scrollTo(
                catProds.offsetTop - getHeaderHeight() + offset + H1_MARGIN,
                {duration: 800, smooth: 'easeInOutQuart'}
            );

            setNeedScroll(false);
        }
    }, [updateCounter]);

    function handleCatLoading(catId: string, isLoaded: boolean) {
        if (IS_CAT_LOADED[catId] !== isLoaded) {
            IS_CAT_LOADED[catId] = isLoaded;

            if (isLoaded)
                setUpdateCounter(prev => prev + 1);
        }
    }

    const children = [];
    for (let i = startIdx; i <= getRightBound(); ++i) {
        const category = categories[i];

        children.push(
            <CatProds
              key={category.id}
              category={category}
              store={store}
              onLoad={isLoaded => handleCatLoading(category.id, isLoaded)}
              getProdCount={getProdCount}
            />
        );
    }

    const navigate = useNavigate();

    function handleCatChange(catIdx: number) {
        if (rightOffset < catIdx)
            setRightOffset(catIdx);

        setNeedScroll(true);
        setUpdateCounter(prev => prev + 1);
        navigate('/wa/products#' + categories[catIdx].id);
    }

    const anonCat = {id: 'anon-cat-id', name: '', photos: []};

    return (<>
        {getCfg().VITE_COMPACT_CATEGORIES && <>
            <Header wide component={
                <HeaderWrapper id='prods-header--search'>
                    <Search />
                </HeaderWrapper>
            } />
            <CatProds
                key={anonCat.id}
                category={anonCat}
                store={store}
                onLoad={isLoaded => handleCatLoading(anonCat.id, isLoaded)}
                getProdCount={getProdCount}
            />
            <Header wide offset={searchHeaderH} component={
                <HeaderWrapper id='prods-header--cats'>
                    <CompactCats categories={categories}
                                 catOffset={catOffset}
                                 onChange={handleCatChange} />
                </HeaderWrapper>
            } />
        </>}
        {children}
    </>);
}
